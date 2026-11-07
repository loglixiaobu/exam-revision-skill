#!/usr/bin/env python3
"""Local-only source extraction; never generates revision prose or calls an API."""
import argparse
import hashlib
import json
import os
import posixpath
import stat
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
FORMULA_PLACEHOLDER = '[OMML公式未转写，需视觉核对]'
IMAGE_PLACEHOLDER = '[图片/图形未解析，需视觉核对]'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'
PPTX_MAIN_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'
PPTX_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
PPTX_MAX_EXPANDED_BYTES = 100 * 1024 * 1024
PPTX_MAX_XML_BYTES = 8 * 1024 * 1024
PPTX_MAX_XML_READ_BYTES = 100 * 1024 * 1024
PPTX_MAX_TEXT_CHARACTERS = 10_000_000
PPTX_MAX_MEMBERS = 10000
PPTX_MAX_XML_NODES = 200000
PPTX_MAX_XML_DEPTH = 128
PPTX_MAX_SLIDES = 5000
PPTX_MAX_COMPRESSION_RATIO = 1000


class PptxSafetyError(ValueError):
    """Unsafe packages fail closed, even when one readable slide exists."""


class _NoDTDTreeBuilder(ET.TreeBuilder):
    def doctype(self, *args):
        raise PptxSafetyError('PPTX XML包含DTD/实体声明，已拒绝解析')


def pptx_xml(z, name):
    """Bounded XML reads; no entity resolution, package extraction or network."""
    size = z.getinfo(name).file_size
    if size > PPTX_MAX_XML_BYTES:
        raise PptxSafetyError('PPTX XML超过8MiB保护阈值，请拆分材料')
    # A small package can reference the same slide or notes thousands of
    # times. Count every read, not just the ZIP's unique member sizes.
    consumed = getattr(z, '_pptx_xml_read_bytes', 0)
    if consumed + size > PPTX_MAX_XML_READ_BYTES:
        raise PptxSafetyError('PPTX累计XML读取量超过保护阈值（包含重复引用），请拆分材料')
    with z.open(name) as stream:
        data = stream.read(PPTX_MAX_XML_BYTES + 1)
    if len(data) > PPTX_MAX_XML_BYTES:
        raise PptxSafetyError('PPTX XML超过8MiB保护阈值，请拆分材料')
    z._pptx_xml_read_bytes = consumed + len(data)
    if z._pptx_xml_read_bytes > PPTX_MAX_XML_READ_BYTES:
        raise PptxSafetyError('PPTX累计XML读取量超过保护阈值（包含重复引用），请拆分材料')
    # Also recognize UTF-16/32 declarations before parsing any internal subset.
    if b'<!DOCTYPE' in data.replace(b'\x00', b'') or b'<!ENTITY' in data.replace(b'\x00', b''):
        raise PptxSafetyError('PPTX XML包含DTD/实体声明，已拒绝解析')
    root = ET.fromstring(data, parser=ET.XMLParser(target=_NoDTDTreeBuilder()))
    strict = {
        '{http://purl.oclc.org/ooxml/presentationml/main}': P,
        '{http://purl.oclc.org/ooxml/drawingml/main}': A,
        '{http://purl.oclc.org/ooxml/officeDocument/relationships}': R,
        '{http://purl.oclc.org/ooxml/officeDocument/math}': M,
    }
    pending, count = [(root, 1)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > PPTX_MAX_XML_NODES or depth > PPTX_MAX_XML_DEPTH:
            raise PptxSafetyError('PPTX XML节点数量或嵌套深度超过保护阈值')
        for old, new in strict.items():
            if node.tag.startswith(old):
                node.tag = new + node.tag[len(old):]
            for key in list(node.attrib):
                if key.startswith(old):
                    node.set(new + key[len(old):], node.attrib.pop(key))
        pending.extend((child, depth + 1) for child in node)
    return root


def pptx_target(part, target):
    """Resolve an OPC part URI, allowing ../ only inside the package root."""
    if any(ord(c) < 32 for c in target):
        raise PptxSafetyError('PPTX关系目标包含控制字符')
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise PptxSafetyError('PPTX内部关系包含外部URI或不支持的目标')
    decoded = unquote(parsed.path, errors='strict')
    if not decoded or '\\' in decoded or ':' in decoded or any(ord(c) < 32 for c in decoded):
        raise PptxSafetyError('PPTX关系目标路径不安全')
    parts = [] if decoded.startswith('/') else part.split('/')[:-1]
    for segment in decoded.split('/'):
        if segment in {'', '.'}:
            continue
        if segment == '..':
            if not parts:
                raise PptxSafetyError('PPTX关系目标越过包根目录，已拒绝路径穿越')
            parts.pop()
        else:
            parts.append(segment)
    if not parts:
        raise PptxSafetyError('PPTX关系目标为空')
    return '/'.join(parts)


def pptx_relationships(z, part, warnings, required=False):
    name = (posixpath.join(posixpath.dirname(part), '_rels', posixpath.basename(part) + '.rels')
            if part else '_rels/.rels')
    if name not in z.namelist():
        if required:
            raise ValueError('PPTX缺少关系文件：' + name)
        return {}
    root = pptx_xml(z, name)
    if root.tag != REL + 'Relationships':
        raise ValueError('PPTX关系文件根元素不正确：' + name)
    rels = {}
    for node in root:
        if node.tag != REL + 'Relationship':
            continue
        rid, kind, target = node.get('Id'), node.get('Type'), node.get('Target')
        if not rid or not kind or not target or rid in rels:
            raise ValueError('PPTX关系ID重复或字段缺失：' + name)
        mode = node.get('TargetMode', 'Internal')
        if mode not in {'Internal', 'External'}:
            raise ValueError('PPTX关系TargetMode无效：' + name)
        if mode == 'External':
            warnings.append(f'{part or "包根目录"}包含外部关系（{rid}）；已跳过，未访问外部资源')
            resolved = None
        else:
            resolved = pptx_target(part, target)
        # Match only the known transitional and Strict relationship families.
        prefixes = ('http://schemas.openxmlformats.org/officeDocument/2006/relationships/',
                    'http://purl.oclc.org/ooxml/officeDocument/relationships/')
        kind = next((kind[len(prefix):] for prefix in prefixes if kind.startswith(prefix)), kind)
        rels[rid] = {'kind': kind, 'target': resolved}
    return rels


def pptx_check_archive(z):
    infos = z.infolist()
    if len(infos) > PPTX_MAX_MEMBERS:
        raise PptxSafetyError('PPTX ZIP成员数量超过保护阈值')
    if sum(info.file_size for info in infos) > PPTX_MAX_EXPANDED_BYTES:
        raise PptxSafetyError('PPTX解压后超过100MiB保护阈值，请拆分材料')
    seen = set()
    for info in infos:
        # ZipInfo.filename is already sanitized: Windows separators become
        # '/' and a NUL truncates the name. Validate the original decoded ZIP
        # name, not the platform-dependent alias, before trusting any member.
        raw_name = info.orig_filename
        name = raw_name[:-1] if raw_name.endswith('/') else raw_name
        if (raw_name != info.filename or not name or name.startswith('/') or '\\' in name or ':' in name
                or any(ord(c) < 32 for c in name)
                or any(bit in {'', '.', '..'} for bit in name.split('/'))):
            raise PptxSafetyError('PPTX ZIP成员路径不安全，已拒绝路径穿越')
        if name in seen:
            raise PptxSafetyError('PPTX ZIP含重复成员名')
        seen.add(name)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise PptxSafetyError('PPTX ZIP含符号链接成员')
        if info.flag_bits & 1:
            raise PptxSafetyError('加密PPTX：请提供经授权解密后的副本')
        if info.file_size > 1024 * 1024 and info.file_size / max(info.compress_size, 1) > PPTX_MAX_COMPRESSION_RATIO:
            raise PptxSafetyError('PPTX ZIP压缩比超过保护阈值，请拆分材料')


def pptx_compatible_children(node):
    """Read a single compatibility branch, never duplicate Choice/Fallback."""
    if node.tag == MC + 'AlternateContent':
        branch = node.find(MC + 'Fallback')
        if branch is None:
            branch = node.find(MC + 'Choice')
        return list(branch) if branch is not None else []
    return list(node)


def pptx_text(node):
    if node.tag == A + 't':
        return node.text or ''
    if node.tag == A + 'br':
        return '\n'
    if node.tag == A + 'tab':
        return '\t'
    if node.tag == M + 'oMath':
        return FORMULA_PLACEHOLDER
    return ''.join(pptx_text(child) for child in pptx_compatible_children(node)) + ('\n' if node.tag == A + 'p' else '')


def pptx_content(root, warnings, label, notes=False):
    """Preserve shape-tree order; do not claim it is visual reading order."""
    tree = root.find('./' + P + 'cSld/' + P + 'spTree')
    if tree is None:
        raise ValueError('缺少cSld/spTree内容结构')
    nodes = list(root.iter())
    local_names = {node.tag.rsplit('}', 1)[-1] for node in nodes}
    tags = {node.tag for node in nodes}
    if P + 'pic' in tags or P + 'cxnSp' in tags:
        warnings.append(label + '包含图片/图形；未做OCR或视觉解析')
    if 'chart' in local_names or 'chartEx' in local_names:
        warnings.append(label + '包含图表；图表标签、数据和坐标关系未提取，需视觉核对')
    if 'relIds' in local_names:
        warnings.append(label + '包含SmartArt；图形层次和文本未提取，需视觉核对')
    if M + 'oMath' in tags:
        warnings.append(label + '包含OMML公式；公式未转写，需视觉核对')
    if local_names & {'videoFile', 'audioFile', 'audioCd', 'audio', 'video', 'media', 'wavAudioFile', 'oleObj', 'control'}:
        warnings.append(label + '包含音视频/嵌入对象/控件等不支持的媒体；未读取或执行')
    if P + 'contentPart' in tags:
        warnings.append(label + '包含墨迹等contentPart扩展内容；未提取，需查看原课件')
    if A + 'buAutoNum' in tags or A + 'buChar' in tags:
        warnings.append(label + '包含项目符号/自动编号；编号与列表层次未展开，需核对')
    if any(any(node.get(key) not in {None, '0', '1', 'false'} for key in ('rowSpan', 'gridSpan'))
           or any(node.get(key) in {'1', 'true'} for key in ('hMerge', 'vMerge')) for node in nodes):
        warnings.append(label + '包含合并单元格；表格被线性化，需核对行列对应关系')
    if MC + 'AlternateContent' in tags:
        warnings.append(label + '包含兼容分支；仅提取一个分支，显示结果需核对')
    if P + 'grpSp' in tags or P + 'timing' in tags:
        warnings.append(label + '包含组合形状或动画；层次/播放顺序未还原')
    if A + 'fld' in tags:
        warnings.append(label + '包含动态字段；只保留文件中的缓存文字，未更新字段')
    chunks, tables = [], 0

    def walk(node):
        nonlocal tables
        if node.tag == P + 'sp':
            placeholder = node.find('./' + P + 'nvSpPr/' + P + 'nvPr/' + P + 'ph')
            if notes and placeholder is not None and placeholder.get('type') in {'sldImg', 'sldNum', 'hdr', 'ftr', 'dt'}:
                return
            properties = node.find('./' + P + 'nvSpPr/' + P + 'cNvSpPr')
            textbox = properties is not None and properties.get('txBox') in {'1', 'true'}
            geometry = (node.find('./' + P + 'spPr/' + A + 'prstGeom') is not None
                        or node.find('./' + P + 'spPr/' + A + 'custGeom') is not None)
            drawing = geometry and placeholder is None and not textbox
            if drawing:
                warnings.append(label + '包含自选形状/图形；仅提取其中的文字，几何关系未解析，需视觉核对')
            body = node.find(A + 'txBody')
            if body is None:
                body = node.find(P + 'txBody')
            if body is not None:
                value = pptx_text(body).strip()
                if value:
                    chunks.append(value)
                elif drawing:
                    # AutoShapes usually contain an empty txBody. An arrow or
                    # diagram node must not disappear just because it has one.
                    chunks.append(IMAGE_PLACEHOLDER)
            elif drawing or (not notes and placeholder is None and not textbox):
                chunks.append(IMAGE_PLACEHOLDER)
        elif node.tag == A + 'tbl':
            tables += 1
            rows = []
            for row in node.findall(A + 'tr'):
                rows.append(' | '.join(' / '.join(pptx_text(p).strip() for p in cell.findall('./' + A + 'txBody/' + A + 'p'))
                                       for cell in row.findall(A + 'tc')))
            chunks.append(f'[表格{tables}]\n' + '\n'.join(rows) + f'\n[表格{tables}结束]')
            warnings.append(label + f'表格{tables}按行线性化；单元格分隔符为 |，需对照原表核对')
        elif node.tag == P + 'pic' or node.tag == P + 'cxnSp':
            chunks.append(IMAGE_PLACEHOLDER)
        elif node.tag.rsplit('}', 1)[-1] in {'chart', 'chartEx'}:
            chunks.append('[图表未解析，需视觉核对]')
        elif node.tag.rsplit('}', 1)[-1] == 'relIds':
            chunks.append('[SmartArt未解析，需视觉核对]')
        elif node.tag in {P + 'oleObj', P + 'control'}:
            chunks.append('[嵌入对象/控件未解析，需查看原课件]')
        elif node.tag == P + 'contentPart':
            chunks.append('[墨迹/扩展内容未解析，需查看原课件]')
        elif node.tag == A + 'graphicData' and not any(
                child.tag == A + 'tbl' or child.tag.rsplit('}', 1)[-1] in {'chart', 'chartEx', 'relIds', 'oleObj'}
                for child in node.iter()):
            chunks.append('[不支持的图形内容未解析，需视觉核对]')
            warnings.append(label + '包含不支持的graphicData图形内容；未提取，需视觉核对')
        else:
            for child in pptx_compatible_children(node):
                walk(child)

    walk(tree)
    if not chunks:
        warnings.append(label + '未提取到文字；空白页或图片/公式等内容需查看原课件')
    return '\n\n'.join(chunks), tables


def pptx_units(path):
    """Extract editable OOXML text and notes, following p:sldIdLst + rels."""
    if Path(path).stat().st_size > PPTX_MAX_ARCHIVE_BYTES:
        raise PptxSafetyError('PPTX文件超过100MiB保护阈值，请拆分材料')
    if not zipfile.is_zipfile(path):
        raise ValueError('不是有效PPTX文件；请在PowerPoint/LibreOffice中另存为.pptx，不能只改后缀')
    warnings, units, extracted_characters = [], [], 0

    def check_text_budget(text):
        nonlocal extracted_characters
        extracted_characters += len(text)
        if extracted_characters > PPTX_MAX_TEXT_CHARACTERS:
            raise PptxSafetyError('PPTX累计提取文字超过保护阈值（包含重复引用），请拆分材料')

    with zipfile.ZipFile(path) as z:
        pptx_check_archive(z)
        content_types = pptx_xml(z, '[Content_Types].xml')
        if content_types.tag != CT + 'Types':
            raise ValueError('PPTX内容类型声明不正确')
        roots = pptx_relationships(z, '', warnings, required=True)
        main = [rel for rel in roots.values() if rel['kind'] == 'officeDocument']
        if len(main) != 1 or not main[0]['target']:
            raise ValueError('PPTX必须有唯一的包内presentation关系')
        part = main[0]['target']
        main_types = [node.get('ContentType') for node in content_types.findall(CT + 'Override')
                      if node.get('PartName') == '/' + part]
        if main_types != [PPTX_MAIN_TYPE]:
            raise ValueError('文件不是标准.pptx演示文稿；请另存为.pptx，不能只改后缀')
        presentation = pptx_xml(z, part)
        if presentation.tag != P + 'presentation':
            raise ValueError('PPTX主文档不是presentation')
        rels = pptx_relationships(z, part, warnings, required=True)
        slides = presentation.findall('./' + P + 'sldIdLst/' + P + 'sldId')
        if not slides or len(slides) > PPTX_MAX_SLIDES:
            raise ValueError('PPTX无幻灯片或幻灯片数量超过保护阈值')
        seen_slides, seen_notes = set(), set()
        for number, reference in enumerate(slides, 1):
            label = f'第{number}页'
            unit = {'locator': f's{number:04d}', 'kind': 'slide', 'text': '', 'slide_number': number}
            units.append(unit)
            try:
                rel = rels.get(reference.get(R + 'id'))
                if not rel or rel['kind'] != 'slide' or not rel['target']:
                    raise ValueError('幻灯片关系缺失、类型不符或指向外部')
                slide_part = rel['target']
                if slide_part in seen_slides:
                    warnings.append(label + '重复引用同一幻灯片部件；保留展示位置，需核对')
                seen_slides.add(slide_part)
                root = pptx_xml(z, slide_part)
                if root.tag != P + 'sld':
                    raise ValueError('幻灯片根元素不是sld')
                unit.update(part=slide_part, hidden=root.get('show', '1') in {'0', 'false'})
                if unit['hidden']:
                    warnings.append(label + '是隐藏幻灯片；仍提取，是否纳入考试范围需确认')
                unit['text'], unit['table_count'] = pptx_content(root, warnings, label)
                check_text_budget(unit['text'])
            except PptxSafetyError:
                raise
            except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
                unit['extraction_failed'] = True
                warnings.append(f'{label}提取失败：{type(exc).__name__}: {exc}；保留页码定位，其他页继续')
                continue
            try:
                slide_rels = pptx_relationships(z, slide_part, warnings)
            except PptxSafetyError:
                raise
            except (ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
                warnings.append(f'{label}附属关系无法解析：{exc}；讲者备注可能缺失')
                continue
            notes_rels = [rel for rel in slide_rels.values() if rel['kind'] == 'notesSlide']
            if len(notes_rels) > 1:
                warnings.append(label + '含多个备注关系；不能确定唯一备注，已跳过，需人工核对')
                continue
            if notes_rels:
                note = {'locator': f'n{number:04d}', 'kind': 'speaker_notes', 'text': '', 'slide_number': number}
                units.append(note)
                try:
                    note_part = notes_rels[0]['target']
                    if not note_part:
                        raise ValueError('备注指向外部，未读取')
                    seen_notes.add(note_part)
                    note['part'] = note_part
                    root = pptx_xml(z, note_part)
                    if root.tag != P + 'notes':
                        raise ValueError('备注根元素不是notes')
                    note['text'], note['table_count'] = pptx_content(root, warnings, label + '讲者备注', notes=True)
                    check_text_budget(note['text'])
                    pptx_relationships(z, note_part, warnings)
                except PptxSafetyError:
                    raise
                except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile) as exc:
                    note['extraction_failed'] = True
                    warnings.append(f'{label}讲者备注提取失败：{type(exc).__name__}: {exc}；需查看原课件')
        names = z.namelist()
        unreferenced = [name for name in names if (name.startswith('ppt/slides/') or name.startswith('ppt/notesSlides/'))
                        and '/_rels/' not in name and name.endswith('.xml') and name not in seen_slides | seen_notes]
        if unreferenced:
            warnings.append(f'有{len(unreferenced)}个未被展示顺序/备注关系引用的幻灯片或备注部件；未提取')
        if any('vba' in name.lower() or name.startswith(('ppt/embeddings/', 'ppt/activeX/', 'ppt/media/')) for name in names):
            warnings.append('包含媒体/嵌入内容/可执行部件；未解包、播放或执行')
    warnings.append('PPTX按展示顺序定位，页内按XML形状树顺序提取，不保证视觉阅读顺序；未渲染，未提取母版/版式/背景/批注，图形、公式和动画需视觉核对')
    return units, list(dict.fromkeys(warnings))


def is_link(path):
    """Recognize symlinks and Windows junction/reparse points on Python 3.10+."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def source_files(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        directory = Path(directory)
        # os.walk may follow Windows junctions even with followlinks=False.
        dirs[:] = [name for name in dirs if not is_link(directory / name)]
        for name in names:
            path = directory / name
            if not is_link(path) and path.is_file():
                yield path


def word_text(element):
    """Preserve visible separators, never invent a plain-text equation."""
    if element.tag == W + 't':
        return element.text or ''
    if element.tag == W + 'tab':
        return '\t'
    if element.tag in {W + 'br', W + 'cr'}:
        return '\n'
    if element.tag == W + 'noBreakHyphen':
        return '\u2011'
    if element.tag == W + 'softHyphen':
        return '\u00ad'
    if element.tag == M + 'oMath':
        return FORMULA_PLACEHOLDER
    if element.tag in {W + 'drawing', W + 'pict', W + 'object'}:
        # Text boxes may have readable text as well as a drawing. Keep that
        # text, but do not pretend it describes the surrounding graphic.
        text = ''.join(word_text(child) for child in element)
        return IMAGE_PLACEHOLDER + ('\n' + text if text.strip() else '')
    text = ''.join(word_text(child) for child in element)
    return text + ('\n' if element.tag == W + 'p' else '')


def word_children(parent, tags):
    """Unwrap content controls/custom XML without changing source order."""
    for child in parent:
        if child.tag in tags:
            yield child
        elif child.tag in {W + 'sdt', W + 'sdtContent', W + 'customXml'}:
            yield from word_children(child, tags)


def docx_units(path):
    warnings = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if sum(i.file_size for i in infos) > 100 * 1024 * 1024:
            raise ValueError('DOCX 解压后超过100MiB保护阈值，请拆分材料')
        root = ET.fromstring(z.read('word/document.xml'))
        body = root.find(W + 'body')
        if body is None:
            raise ValueError('缺少正文')
        if root.findall('.//' + M + 'oMath'):
            warnings.append('包含OMML公式；公式未转写，必须视觉核对')
        if any(root.findall('.//' + W + tag) for tag in ('drawing', 'pict', 'object')):
            warnings.append('包含图片/图形；未做视觉解析')
        if root.findall('.//' + W + 'txbxContent'):
            warnings.append('包含文本框；阅读顺序需视觉核对')
        if root.findall('.//' + W + 'del') or root.findall('.//' + W + 'ins'):
            warnings.append('包含修订；需核对正文最终状态')
        if root.findall('.//' + W + 'numPr'):
            warnings.append('包含自动编号；编号未展开，需对照原文核对列表层次')
        if root.findall('.//' + W + 'altChunk'):
            warnings.append('包含altChunk外部导入内容；未提取，需查看原文')
        if any(root.findall('.//' + W + tag) for tag in ('gridSpan', 'vMerge', 'hMerge')):
            warnings.append('包含合并单元格；表格被线性化，需核对行列对应关系')
        if any(table.findall('.//' + W + 'tbl') for table in root.iter(W + 'tbl')):
            warnings.append('包含嵌套表格；层次被线性化，需视觉核对')
        known = {W + tag for tag in ('p', 'tbl', 'sdt', 'sdtContent', 'sdtPr',
                                      'sdtEndPr', 'customXml', 'customXmlPr',
                                      'sectPr', 'altChunk', 'bookmarkStart',
                                      'bookmarkEnd', 'proofErr', 'permStart',
                                      'permEnd', 'commentRangeStart', 'commentRangeEnd')}
        def check_body_structure(container):
            for child in container:
                if child.tag not in known:
                    warnings.append('未处理正文结构：' + child.tag.rsplit('}', 1)[-1] + '；需查看原文')
                elif child.tag in {W + 'sdt', W + 'sdtContent', W + 'customXml'}:
                    check_body_structure(child)

        check_body_structure(body)
        extras = [n for n in z.namelist() if n.startswith(('word/header', 'word/footer', 'word/footnotes', 'word/endnotes', 'word/comments')) and n.endswith('.xml')]
        if extras:
            warnings.append('附属内容未纳入正文：' + ', '.join(extras))
        out = []
        for child in word_children(body, {W + 'p', W + 'tbl'}):
            if child.tag == W + 'p':
                text = word_text(child).strip()
                kind = 'paragraph'
            elif child.tag == W + 'tbl':
                rows = []
                for row in word_children(child, {W + 'tr'}):
                    rows.append(' | '.join(' / '.join(word_text(p).strip() for p in cell.iter(W + 'p')) for cell in word_children(row, {W + 'tc'})))
                text = '\n'.join(rows)
                kind = 'table'
            else:
                continue
            if text.strip():
                out.append({'locator': f'b{len(out)+1:04d}', 'kind': kind, 'text': text.strip()})
        if not out:
            warnings.append('未提取正文；可能只有图片或公式')
        return out, warnings


def pdf_has_painted_image(page, reader):
    """Inspect draw operations, including Form XObjects, without image decoding.

    An image merely listed in the resources may not be displayed on this page.
    Do not label it a scan, and do not require Pillow to inspect image assets.
    """
    from pypdf.generic import ContentStream

    def inspect(stream, resources, ancestors=(), depth=0):
        if stream is None:
            return False
        if depth > 32:
            raise ValueError('PDF图形嵌套层数超过检查阈值')
        resources = resources.get_object() if resources is not None else {}
        objects = resources.get('/XObject', {})
        objects = objects.get_object() if hasattr(objects, 'get_object') else objects
        contents = stream if isinstance(stream, ContentStream) else ContentStream(stream, reader)
        for operands, operator in contents.operations:
            if operator == b'INLINE IMAGE':
                return True
            if operator != b'Do' or not operands:
                continue
            obj = objects[operands[0]].get_object()
            if obj.get('/Subtype') == '/Image':
                return True
            if obj.get('/Subtype') == '/Form':
                identity = id(obj)
                if identity in ancestors:
                    raise ValueError('PDF图形存在循环引用')
                if inspect(obj, obj.get('/Resources', resources), ancestors + (identity,), depth + 1):
                    return True
        return False

    return inspect(page.get_contents(), page.get('/Resources'))


def pdf_units(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError('缺少pypdf；请安装requirements.txt中的依赖')
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError('加密PDF：请提供经授权解密后的副本')
    units, warnings = [], []
    for n, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ''
        except Exception as exc:
            text = ''
            warnings.append(f'第{n}页文字提取失败：{type(exc).__name__}: {exc}；需查看原文，其他页继续提取')
        units.append({'locator': f'p{n:04d}', 'kind': 'page', 'text': text.strip()})
        if len(''.join(text.split())) < 20:
            warnings.append(f'第{n}页文字过少或为空，需要视觉/OCR检查')
        if '\ufffd' in text:
            warnings.append(f'第{n}页包含替换字符，编码或公式可能损坏')
        try:
            if pdf_has_painted_image(page, reader):
                warnings.append(f'第{n}页包含图片；可能有扫描正文或图表未提取，需要视觉/OCR检查')
        except Exception as exc:
            warnings.append(f'第{n}页图片检查失败：{type(exc).__name__}: {exc}；需视觉核对')
    warnings.append('PDF仅提取文字；图表、公式、列阅读顺序尚未视觉验证')
    return units, warnings


def run(source, out):
    if is_link(Path(source)):
        raise ValueError('输入不能是符号链接或junction；请直接提供实际文件或目录')
    if is_link(Path(out)):
        raise ValueError('输出不能是符号链接或junction；请使用新的目录，避免覆盖')
    source, out = Path(source).resolve(), Path(out).resolve()
    if not source.exists():
        raise ValueError('输入不存在')
    if out.exists():
        raise ValueError('输出目录已存在；请使用新的目录，避免覆盖')
    paths = [source] if source.is_file() else sorted(source_files(source), key=lambda x: str(x).casefold())
    paths = [p for p in paths if not p.name.startswith('~$') and p.name.casefold() not in {'.ds_store', 'thumbs.db', 'desktop.ini'}]
    files, md = [], ['# 提取来源（未经过视觉校对）\n']
    for n, path in enumerate(paths, 1):
        sid = f'S{n:03d}'
        rel = path.name if source.is_file() else path.relative_to(source).as_posix()
        entry = {'id': sid, 'file': rel, 'sha256': None, 'status': 'unsupported', 'warnings': [], 'units': []}
        suffix = path.suffix.lower()
        if suffix not in {'.pdf', '.docx', '.pptx'}:
            if suffix == '.ppt':
                entry['warnings'] = ['旧.ppt暂不支持；请用PowerPoint或LibreOffice另存为.pptx后重试，不能只改后缀。也可导出PDF，但讲者备注可能丢失']
            else:
                entry['warnings'] = ['旧DOC需转换为DOCX'] if suffix == '.doc' else ['不支持此格式']
        else:
            try:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                entry['sha256'] = digest.hexdigest()
                units, warnings = {'.pdf': pdf_units, '.docx': docx_units, '.pptx': pptx_units}[suffix](path)
                records = []
                for unit in units:
                    record = {'id': sid + ':' + unit['locator'], 'kind': unit['kind'], 'characters': len(unit['text'])}
                    record.update({key: unit[key] for key in ('slide_number', 'part', 'hidden', 'table_count', 'extraction_failed') if key in unit})
                    records.append(record)
                entry.update(status='extracted_with_warnings' if warnings else 'extracted', units=records, warnings=warnings)
                md.append(f'## {sid} — {rel}\n')
                for u in units:
                    label = ''
                    if u['kind'] in {'slide', 'speaker_notes'}:
                        label = f"第{u['slide_number']}页" + ('讲者备注' if u['kind'] == 'speaker_notes' else '幻灯片')
                        label += '（隐藏）' if u.get('hidden') else ''
                        label += '（提取失败，需核对原课件）' if u.get('extraction_failed') else ''
                        label += '\n\n'
                    md.append(f"### [{sid}:{u['locator']}]\n\n{label}{u['text'] or '(无可提取文字)'}\n")
            except Exception as exc:
                entry.update(status='failed', warnings=[f'{type(exc).__name__}: {exc}'])
        files.append(entry)
    if not files:
        raise ValueError('目录中没有文件')
    out.mkdir(parents=True)
    (out / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'source_root': str(source), 'files': files}, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'sources.md').write_text('\n'.join(md), encoding='utf-8')
    print(json.dumps({'files': len(files), 'extracted': sum(f['status'].startswith('extracted') for f in files), 'failed': sum(f['status'] == 'failed' for f in files), 'unsupported': sum(f['status'] == 'unsupported' for f in files), 'output': str(out)}, ensure_ascii=True))
    return 2 if any(f['status'] in {'failed', 'unsupported'} for f in files) else 0


if __name__ == '__main__':
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        sys.exit(run(args.input, args.out))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
