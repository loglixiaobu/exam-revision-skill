import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fixtures.mixed_sources import mixed_docx, mixed_pdf, paragraph, write_docx

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('extract_mixed_sources', ROOT / 'scripts/extract_sources.py')
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


class MixedSourceTests(unittest.TestCase):
    def test_docx_controlled_paragraph_and_table_preserve_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mixed.docx'
            mixed_docx(path)
            units, warnings = extract.docx_units(path)
            texts = [u['text'] for u in units]
            self.assertIn('CONTROLLED NOTE: Binary search requires sorted input.', texts)
            self.assertEqual(units[3]['kind'], 'table')
            self.assertIn('Binary search | Sorted input', units[3]['text'])
            self.assertEqual([u['locator'] for u in units], [f'b{n:04d}' for n in range(1, len(units) + 1)])

    def test_docx_tabs_breaks_and_visual_only_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mixed.docx'
            mixed_docx(path)
            units, warnings = extract.docx_units(path)
            texts = [u['text'] for u in units]
            self.assertIn('Step 1\tSort first\nStep 2\tSearch', texts)
            self.assertIn('[OMML公式未转写，需视觉核对]', texts)
            self.assertIn('[图片/图形未解析，需视觉核对]', texts)
            self.assertTrue(any('OMML' in w for w in warnings))
            self.assertTrue(any('图片/图形' in w for w in warnings))
            self.assertFalse(any('1n' in text for text in texts), 'Do not flatten a fraction into an invented formula')

    def test_docx_unhandled_body_content_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'imported.docx'
            write_docx(path, paragraph('Visible text') + '<w:altChunk r:id="rIdImport"/>')
            units, warnings = extract.docx_units(path)
            self.assertEqual(units[0]['text'], 'Visible text')
            self.assertTrue(any('altChunk' in warning for warning in warnings))

    def test_inline_content_control_is_not_reported_as_dropped_body(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inline.docx'
            write_docx(path, '<w:p><w:sdt><w:sdtContent><w:r><w:t>Inline note</w:t></w:r></w:sdtContent></w:sdt></w:p>')
            units, warnings = extract.docx_units(path)
            self.assertEqual(units[0]['text'], 'Inline note')
            self.assertFalse(warnings)

    def test_docx_custom_xml_and_table_row_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'controls.docx'
            body = '<w:customXml>' + paragraph('First paragraph') + '</w:customXml>'
            body += '<w:tbl><w:sdt><w:sdtContent><w:tr><w:sdt><w:sdtContent><w:tc>'
            body += paragraph('Controlled cell') + '</w:tc></w:sdtContent></w:sdt></w:tr></w:sdtContent></w:sdt></w:tbl>'
            write_docx(path, body)
            units, warnings = extract.docx_units(path)
            self.assertEqual([u['text'] for u in units], ['First paragraph', 'Controlled cell'])
            self.assertFalse(warnings)

    def test_merged_nested_table_and_automatic_numbering_warn(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.docx'
            body = '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>List item</w:t></w:r></w:p>'
            body += '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
            body += paragraph('Outer cell') + '<w:tbl><w:tr><w:tc>' + paragraph('Inner cell')
            body += '</w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>'
            write_docx(path, body)
            units, warnings = extract.docx_units(path)
            self.assertEqual(units[1]['text'], 'Outer cell / Inner cell')
            for term in ('合并单元格', '嵌套表格', '自动编号'):
                self.assertTrue(any(term in warning for warning in warnings), warnings)

    def test_pdf_scan_and_mixed_pages_get_local_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mixed.pdf'
            mixed_pdf(path)
            units, warnings = extract.pdf_units(path)
            self.assertEqual(len(units), 4)
            self.assertIn('Binary search', units[0]['text'])
            self.assertIn('Sorted input', units[0]['text'])
            self.assertEqual(units[1]['text'], '')
            self.assertTrue(any('第2页' in w and '文字过少' in w for w in warnings))
            for number in (2, 3, 4):
                self.assertTrue(any(f'第{number}页' in w and '图片' in w for w in warnings), warnings)
            self.assertFalse(any('第1页' in w and '图片' in w for w in warnings), warnings)

    def test_one_pdf_page_extraction_error_does_not_discard_other_pages(self):
        from pypdf import PageObject
        original = PageObject.extract_text

        def fail_second_page(page, *args, **kwargs):
            if page.page_number == 1:
                raise ValueError('Deliberate unreadable page regression')
            return original(page, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'partly-readable.pdf'
            mixed_pdf(path)
            with patch.object(PageObject, 'extract_text', fail_second_page):
                units, warnings = extract.pdf_units(path)
            self.assertEqual(len(units), 4)
            self.assertIn('Search methods revision', units[0]['text'])
            self.assertIn('Mixed page', units[2]['text'])
            self.assertTrue(any('第2页文字提取失败' in w for w in warnings))

    def test_pdf_inline_image_is_detected_without_pillow(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'inline-image.pdf'
            writer = PdfWriter()
            page = writer.add_blank_page(width=100, height=100)
            contents = DecodedStreamObject()
            contents.set_data(b'q 10 0 0 10 20 20 cm BI /W 1 /H 1 /CS /RGB /BPC 8 ID \x00\x00\x00 EI Q')
            page[NameObject('/Contents')] = writer._add_object(contents)
            with path.open('wb') as output:
                writer.write(output)
            units, warnings = extract.pdf_units(path)
            self.assertTrue(any('第1页包含图片' in w for w in warnings), warnings)

    def test_batch_sources_and_manifest_keep_visual_only_locators(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input', Path(directory) / 'output'
            source.mkdir()
            mixed_docx(source / '01-notes.docx')
            mixed_pdf(source / '02-slides.pdf')
            self.assertEqual(extract.run(source, output), 0)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            markdown = (output / 'sources.md').read_text(encoding='utf-8')
            self.assertEqual([f['status'] for f in manifest['files']], ['extracted_with_warnings'] * 2)
            self.assertIn('[OMML公式未转写，需视觉核对]', markdown)
            self.assertIn('[图片/图形未解析，需视觉核对]', markdown)
            self.assertIn('### [S002:p0002]', markdown)
            for entry in manifest['files']:
                self.assertEqual(len(entry['sha256']), 64)
                for unit in entry['units']:
                    self.assertIn(f"### [{unit['id']}]", markdown)

    def test_source_root_symlink_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / 'real.docx'
            mixed_docx(real)
            link = root / 'link.docx'
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest('Symlink creation is unavailable on this platform')
            with self.assertRaisesRegex(ValueError, '符号链接'):
                extract.run(link, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_nested_symlink_file_and_directory_are_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, outside = root / 'input', root / 'outside'
            source.mkdir()
            outside.mkdir()
            mixed_docx(source / 'visible.docx')
            mixed_docx(outside / 'not-in-input.docx')
            try:
                os.symlink(outside, source / 'linked-directory', target_is_directory=True)
                os.symlink(outside / 'not-in-input.docx', source / 'linked-file.docx')
            except (OSError, NotImplementedError):
                self.skipTest('Symlink creation is unavailable on this platform')
            self.assertEqual(extract.run(source, root / 'output'), 0)
            manifest = json.loads((root / 'output/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual([f['file'] for f in manifest['files']], ['visible.docx'])

    def test_windows_reparse_attribute_is_detected_on_all_platforms(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=info):
            self.assertTrue(extract.is_link(Path('junction')))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction integration test')
    def test_windows_junction_root_rejected_and_descendant_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, outside = root / 'input', root / 'outside'
            source.mkdir()
            outside.mkdir()
            mixed_docx(source / 'visible.docx')
            mixed_docx(outside / 'not-in-input.docx')
            junction = source / 'junction'
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(extract.is_link(junction))
            with self.assertRaisesRegex(ValueError, 'junction'):
                extract.run(junction, root / 'rejected')
            self.assertEqual(extract.run(source, root / 'output'), 0)
            manifest = json.loads((root / 'output/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual([f['file'] for f in manifest['files']], ['visible.docx'])


if __name__ == '__main__':
    unittest.main()
