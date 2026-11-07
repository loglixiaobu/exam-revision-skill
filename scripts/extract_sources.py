#!/usr/bin/env python3
"""Local-only source extraction; never generates revision prose or calls an API."""
import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
FORMULA_PLACEHOLDER = '[OMML公式未转写，需视觉核对]'
IMAGE_PLACEHOLDER = '[图片/图形未解析，需视觉核对]'


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
        if suffix not in {'.pdf', '.docx'}:
            entry['warnings'] = ['旧DOC需转换为DOCX'] if suffix == '.doc' else ['不支持此格式']
        else:
            try:
                entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                units, warnings = pdf_units(path) if suffix == '.pdf' else docx_units(path)
                entry.update(status='extracted_with_warnings' if warnings else 'extracted', units=[{'id': sid + ':' + u['locator'], 'kind': u['kind'], 'characters': len(u['text'])} for u in units], warnings=warnings)
                md.append(f'## {sid} — {rel}\n')
                for u in units:
                    md.append(f"### [{sid}:{u['locator']}]\n\n{u['text'] or '(无可提取文字)'}\n")
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
