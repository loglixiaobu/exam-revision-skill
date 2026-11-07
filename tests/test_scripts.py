import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
extract = module('extract_sources')
check = module('check_pack')

class Tests(unittest.TestCase):

    def docx(self, path):
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><w:body><w:p><w:r><w:t>二分查找要求序列有序。</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>算法</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>二分</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath></w:p></w:body></w:document>'
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('word/document.xml', xml)

    def test_docx_order_and_formula_warning(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a.docx'
            self.docx(p)
            units, w = extract.docx_units(p)
            self.assertEqual([x['kind'] for x in units], ['paragraph', 'table'])
            self.assertIn('二分查找', units[0]['text'])
            self.assertTrue(any(('OMML' in x for x in w)))

    def test_partial_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / 'in'
            src.mkdir()
            self.docx(src / 'a.docx')
            (src / 'b.doc').write_bytes(b'old')
            out = root / 'out'
            self.assertEqual(extract.run(src, out), 2)
            data = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['files']), 2)
            self.assertEqual(data['files'][1]['status'], 'unsupported')
            with self.assertRaises(ValueError):
                extract.run(src, out)

    def test_ignore_editor_and_os_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / 'in'
            src.mkdir()
            self.docx(src / 'a.docx')
            for name in ['~$a.docx', '.DS_Store', 'Thumbs.db', 'desktop.ini']:
                (src / name).write_bytes(b'temp')
            out = root / 'out'
            self.assertEqual(extract.run(src, out), 0)
            files = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))['files']
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]['id'], 'S001')

    def test_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.docx'
            p.write_text('not a zip', encoding='utf-8')
            out = Path(d) / 'out'
            self.assertEqual(extract.run(p, out), 2)
            self.assertEqual(json.loads((out / 'manifest.json').read_text(encoding='utf-8'))['files'][0]['status'], 'failed')

    def test_extract_cli_ascii_console(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            src = root / '中文.docx'
            self.docx(src)
            out = root / '复习包'
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/extract_sources.py'), str(src), '--out', str(out)], env={**os.environ, 'PYTHONIOENCODING': 'ascii'}, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['extracted'], 1)

    def test_missing_input(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                extract.run(Path(d) / 'missing', Path(d) / 'out')

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                extract.run(d, Path(d) / 'out')

    def test_pdf_blank_warning(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'blank.pdf'
            w = PdfWriter()
            w.add_blank_page(width=200, height=200)
            w.write(p)
            units, warnings = extract.pdf_units(p)
            self.assertEqual(units[0]['locator'], 'p0001')
            self.assertTrue(any(('文字过少' in x for x in warnings)))

    def test_encrypted_pdf(self):
        from pypdf import PdfWriter
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'enc.pdf'
            w = PdfWriter()
            w.add_blank_page(width=200, height=200)
            w.encrypt('test-only')
            w.write(p)
            with self.assertRaises(ValueError):
                extract.pdf_units(p)

    def test_pack_invalid_reference(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / '_sources').mkdir()
            (root / '_sources/manifest.json').write_text('{"files":[{"units":[{"id":"S001:p0001"}]}]}', encoding='utf-8')
            for name in ['00-开始阅读.md', '01-知识地图.md', '03-考前速查.md', '04-覆盖与待核对.md']:
                (root / name).write_text('ok', encoding='utf-8')
            (root / '02-详细复习.md').write_text('[S999:p0001]', encoding='utf-8')
            (root / '练习卷').mkdir()
            (root / '答案').mkdir()
            (root / '练习卷/A-题目.md').write_text('题目', encoding='utf-8')
            (root / '答案/A-解析.md').write_text('答案', encoding='utf-8')
            self.assertTrue(any(('无效引用' in x for x in check.check(root))))
            (root / '02-详细复习.md').write_text('[S001:p0001]', encoding='utf-8')
            self.assertEqual(check.check(root), [])
if __name__ == '__main__':
    unittest.main()
