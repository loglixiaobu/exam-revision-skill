#!/usr/bin/env python3
"""Local-only source extraction; never generates revision prose or calls an API."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'


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
        if root.findall('.//' + W + 'drawing') or root.findall('.//' + W + 'pict'):
            warnings.append('包含图片/图形；未做视觉解析')
        if root.findall('.//' + W + 'txbxContent'):
            warnings.append('包含文本框；阅读顺序需视觉核对')
        if root.findall('.//' + W + 'del') or root.findall('.//' + W + 'ins'):
            warnings.append('包含修订；需核对正文最终状态')
        extras = [n for n in z.namelist() if n.startswith(('word/header', 'word/footer', 'word/footnotes', 'word/endnotes', 'word/comments')) and n.endswith('.xml')]
        if extras:
            warnings.append('附属内容未纳入正文：' + ', '.join(extras))
        out = []
        for child in body:
            if child.tag == W + 'p':
                text = ''.join(x.text or '' for x in child.iter(W + 't'))
                kind = 'paragraph'
            elif child.tag == W + 'tbl':
                rows = []
                for row in child.findall(W + 'tr'):
                    rows.append(' | '.join(' / '.join(''.join(t.text or '' for t in p.iter(W + 't')) for p in cell.iter(W + 'p')) for cell in row.findall(W + 'tc')))
                text = '\n'.join(rows)
                kind = 'table'
            else:
                continue
            if text.strip():
                out.append({'locator': f'b{len(out)+1:04d}', 'kind': kind, 'text': text.strip()})
        if not out:
            warnings.append('未提取正文；可能只有图片或公式')
        return out, warnings


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
        text = page.extract_text() or ''
        units.append({'locator': f'p{n:04d}', 'kind': 'page', 'text': text.strip()})
        if len(text.strip()) < 20:
            warnings.append(f'第{n}页文字过少或为空，需要视觉/OCR检查')
        if '\ufffd' in text:
            warnings.append(f'第{n}页包含替换字符，编码或公式可能损坏')
    warnings.append('PDF仅提取文字；图表、公式、列阅读顺序尚未视觉验证')
    return units, warnings


def run(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    if not source.exists():
        raise ValueError('输入不存在')
    if out.exists():
        raise ValueError('输出目录已存在；请使用新的目录，避免覆盖')
    paths = [source] if source.is_file() else sorted((p for p in source.rglob('*') if p.is_file() and not p.is_symlink()), key=lambda x: str(x).casefold())
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
