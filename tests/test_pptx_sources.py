import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings as python_warnings
import zipfile

from fixtures.pptx_sources import (
    A, MAIN_TYPE, NS, P, R, basic_parts, mixed_pptx, paragraph,
    relationships, shape, slide, table, write_pptx,
)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('extract_pptx_sources', ROOT / 'scripts/extract_sources.py')
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


class PptxSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'course.pptx'

    def read(self, parts=None):
        write_pptx(self.path, parts)
        return extract.pptx_units(self.path)

    def test_actual_presentation_order_not_sorted_filenames(self):
        units, warnings = self.read()
        self.assertEqual([unit['locator'] for unit in units], ['s0001', 'n0001', 's0002'])
        self.assertIn('First displayed slide', units[0]['text'])
        self.assertIn('Second displayed slide', units[2]['text'])
        self.assertEqual(units[0]['part'], 'ppt/slides/slide9.xml')
        self.assertEqual(units[2]['part'], 'ppt/slides/slide2.xml')

    def test_tables_are_identifiable_and_remain_in_shape_order(self):
        units, _ = self.read()
        first = units[0]['text']
        self.assertLess(first.index('First displayed'), first.index('[表格1]'))
        self.assertLess(first.index('[表格1结束]'), first.index('End of first'))
        self.assertIn('Binary search | Sorted input', first)
        self.assertEqual(units[0]['table_count'], 1)
        self.assertEqual(units[0]['kind'], 'slide')

    def test_speaker_notes_are_distinct_and_filter_boilerplate(self):
        units, _ = self.read()
        note = units[1]
        self.assertEqual(note['kind'], 'speaker_notes')
        self.assertEqual(note['slide_number'], 1)
        self.assertIn('Instructor note', note['text'])
        self.assertNotIn('MUST NOT BECOME NOTES', note['text'])
        self.assertNotIn('Instructor note', units[0]['text'])

    def test_visual_formula_hidden_and_unsupported_media_warnings(self):
        mixed_pptx(self.path)
        units, warnings = extract.pptx_units(self.path)
        unit = units[2]
        self.assertTrue(unit['hidden'])
        for text in ('OMML公式未转写', '图片/图形未解析', '图表未解析', 'SmartArt未解析', '嵌入对象/控件未解析'):
            self.assertIn(text, unit['text'])
        self.assertNotIn('1n', unit['text'], 'Fractions must not become invented plain text')
        for text in ('隐藏幻灯片', '图表', 'SmartArt', 'OMML', '不支持的媒体', '阅读顺序', '母版/版式/背景/批注'):
            self.assertTrue(any(text in warning for warning in warnings), warnings)

    def test_external_hyperlink_and_video_are_not_fetched(self):
        parts = basic_parts()
        parts['ppt/slides/_rels/slide2.xml.rels'] = relationships([
            ('url', 'hyperlink', 'https://example.invalid/never-fetch', 'External'),
            ('video', 'video', 'file:///private/video.mp4', 'External')])
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
            units, warnings = self.read(parts)
        self.assertIn('Second displayed', units[-1]['text'])
        self.assertEqual(sum('未访问外部资源' in warning for warning in warnings), 2)

    def test_missing_slide_relationship_keeps_position_and_other_slides(self):
        parts = basic_parts()
        parts['ppt/_rels/presentation.xml.rels'] = relationships([('firstFile', 'slide', 'slides/slide2.xml')])
        units, warnings = self.read(parts)
        self.assertEqual([unit['locator'] for unit in units], ['s0001', 's0002'])
        self.assertTrue(units[0]['extraction_failed'])
        self.assertEqual(units[0]['text'], '')
        self.assertIn('Second displayed', units[1]['text'])
        self.assertTrue(any('第1页提取失败' in warning for warning in warnings))

    def test_external_slide_relationship_keeps_position_without_fetching(self):
        parts = basic_parts()
        parts['ppt/_rels/presentation.xml.rels'] = relationships([
            ('secondFile', 'slide', 'https://example.invalid/slides.xml', 'External'),
            ('firstFile', 'slide', 'slides/slide2.xml')])
        units, warnings = self.read(parts)
        self.assertTrue(units[0]['extraction_failed'])
        self.assertIn('Second displayed', units[-1]['text'])
        self.assertTrue(any('外部关系' in warning for warning in warnings))

    def test_missing_and_malformed_slide_parts_do_not_hide_other_slides(self):
        for bad_value in (None, '<p:sld', '<notASlide/>'):
            with self.subTest(bad_value=bad_value):
                parts = basic_parts()
                if bad_value is None:
                    del parts['ppt/slides/slide9.xml']
                else:
                    parts['ppt/slides/slide9.xml'] = bad_value
                units, warnings = self.read(parts)
                self.assertTrue(units[0]['extraction_failed'])
                self.assertEqual(units[-1]['locator'], 's0002')
                self.assertIn('Second displayed', units[-1]['text'])

    def test_missing_or_external_notes_keep_a_failed_notes_locator(self):
        for target, mode in (('../notesSlides/missing.xml', 'Internal'), ('https://example.invalid/notes', 'External')):
            with self.subTest(target=target):
                parts = basic_parts()
                parts['ppt/slides/_rels/slide9.xml.rels'] = relationships([('note', 'notesSlide', target, mode)])
                units, warnings = self.read(parts)
                self.assertEqual(units[1]['locator'], 'n0001')
                self.assertTrue(units[1]['extraction_failed'])
                self.assertTrue(any('第1页讲者备注提取失败' in warning for warning in warnings))

    def test_empty_and_image_only_slides_keep_locators(self):
        parts = basic_parts()
        parts['ppt/slides/slide9.xml'] = slide('')
        parts['ppt/slides/slide2.xml'] = slide('<p:pic><p:nvPicPr/></p:pic>')
        units, warnings = self.read(parts)
        self.assertEqual(units[0]['text'], '')
        self.assertEqual(units[-1]['text'], extract.IMAGE_PLACEHOLDER)
        self.assertTrue(any('第1页未提取到文字' in warning for warning in warnings))

    def test_line_breaks_fields_group_shapes_and_bullets(self):
        parts = basic_parts()
        body = ('<a:p><a:pPr><a:buAutoNum type="arabicPeriod"/></a:pPr>'
                '<a:r><a:t>First</a:t></a:r><a:br/><a:r><a:t>Second</a:t></a:r>'
                '<a:fld id="test" type="date"><a:t>Cached field</a:t></a:fld></a:p>')
        parts['ppt/slides/slide2.xml'] = slide('<p:grpSp>' + shape(body=body) + '</p:grpSp>')
        units, warnings = self.read(parts)
        self.assertEqual(units[-1]['text'], 'First\nSecondCached field')
        for text in ('自动编号', '组合形状', '动态字段'):
            self.assertTrue(any(text in warning for warning in warnings))

    def test_alternate_content_does_not_duplicate_text(self):
        parts = basic_parts()
        parts['ppt/slides/slide2.xml'] = slide('<mc:AlternateContent><mc:Choice Requires="a">'
            + shape('Choice text') + '</mc:Choice><mc:Fallback>' + shape('Fallback text')
            + '</mc:Fallback></mc:AlternateContent>')
        units, warnings = self.read(parts)
        self.assertEqual(units[-1]['text'], 'Fallback text')
        self.assertTrue(any('兼容分支' in warning for warning in warnings))

    def test_merged_cells_warn_without_inventing_spanned_values(self):
        parts = basic_parts()
        parts['ppt/slides/slide2.xml'] = slide(table([['Merged', '']]).replace('<a:tc>', '<a:tc gridSpan="2">', 1))
        units, warnings = self.read(parts)
        self.assertTrue(any('合并单元格' in warning for warning in warnings))
        self.assertEqual(units[-1]['text'].count('Merged'), 1)

    def test_ink_and_unknown_graphics_have_visible_omission_markers(self):
        parts = basic_parts()
        parts['ppt/slides/slide2.xml'] = slide('<p:contentPart r:id="ink"/>'
            '<p:graphicFrame><a:graphic><a:graphicData uri="urn:unknown">'
            '<unknownDrawing/></a:graphicData></a:graphic></p:graphicFrame>')
        units, warnings = self.read(parts)
        self.assertIn('墨迹/扩展内容未解析', units[-1]['text'])
        self.assertIn('不支持的图形内容未解析', units[-1]['text'])
        self.assertTrue(any('graphicData' in warning for warning in warnings))

    def test_empty_autoshapes_do_not_disappear_behind_empty_text_bodies(self):
        parts = basic_parts()
        arrow = shape('').replace('<p:spPr/>', '<p:spPr><a:prstGeom prst="rightArrow"><a:avLst/></a:prstGeom></p:spPr>')
        oval = shape('').replace('<p:spPr/>', '<p:spPr><a:prstGeom prst="ellipse"><a:avLst/></a:prstGeom></p:spPr>')
        parts['ppt/slides/slide2.xml'] = slide(shape('Diagram title', placeholder='title') + arrow + oval)
        units, warnings = self.read(parts)
        self.assertIn('Diagram title', units[-1]['text'])
        self.assertEqual(units[-1]['text'].count(extract.IMAGE_PLACEHOLDER), 2)
        self.assertTrue(any('第2页包含自选形状' in warning for warning in warnings))

    def test_empty_textboxes_and_placeholders_do_not_create_visual_warnings(self):
        parts = basic_parts()
        textbox = shape('').replace('<p:cNvSpPr/>', '<p:cNvSpPr txBox="1"/>').replace(
            '<p:spPr/>', '<p:spPr><a:prstGeom prst="rect"/></p:spPr>')
        placeholder = shape('', placeholder='body').replace(
            '<p:spPr/>', '<p:spPr><a:prstGeom prst="rect"/></p:spPr>')
        parts['ppt/slides/slide2.xml'] = slide(shape('Visible title') + textbox + placeholder)
        units, warnings = self.read(parts)
        self.assertEqual(units[-1]['text'], 'Visible title')
        self.assertFalse(any('第2页包含自选形状' in warning for warning in warnings))

    def test_strict_ooxml_namespace_aliases(self):
        replacements = {
            P: 'http://purl.oclc.org/ooxml/presentationml/main',
            A: 'http://purl.oclc.org/ooxml/drawingml/main',
            R: 'http://purl.oclc.org/ooxml/officeDocument/relationships',
        }
        parts = basic_parts()
        for name in parts:
            for old, new in replacements.items():
                parts[name] = parts[name].replace(old, new)
        units, _ = self.read(parts)
        self.assertIn('First displayed', units[0]['text'])
        self.assertIn('Instructor note', units[1]['text'])

    def test_package_absolute_and_percent_encoded_part_targets(self):
        parts = basic_parts()
        parts['ppt/_rels/presentation.xml.rels'] = relationships([
            ('secondFile', 'slide', '/ppt/slides/slide%39.xml'),
            ('firstFile', 'slide', 'slides/slide2.xml')])
        units, _ = self.read(parts)
        self.assertIn('First displayed', units[0]['text'])

    def test_orphan_slide_is_not_invented_as_an_extra_displayed_slide(self):
        parts = basic_parts()
        parts['ppt/slides/slide1.xml'] = slide(shape('Not displayed.'))
        units, warnings = self.read(parts)
        self.assertEqual(len([unit for unit in units if unit['kind'] == 'slide']), 2)
        self.assertFalse(any('Not displayed.' in unit['text'] for unit in units))
        self.assertTrue(any('未被展示顺序' in warning for warning in warnings))

    def test_duplicate_or_invalid_relationship_ids_are_not_silently_guessed(self):
        for rels in (relationships([('x', 'slide', 'slides/slide2.xml'), ('x', 'slide', 'slides/slide9.xml')]),
                     relationships([('', 'slide', 'slides/slide2.xml')])):
            with self.subTest(rels=rels):
                parts = basic_parts()
                parts['ppt/_rels/presentation.xml.rels'] = rels
                with self.assertRaisesRegex(ValueError, 'ID重复或字段缺失'):
                    self.read(parts)

    def test_wrong_slide_relationship_type_is_rejected_locally(self):
        parts = basic_parts()
        parts['ppt/_rels/presentation.xml.rels'] = relationships([
            ('secondFile', 'image', 'slides/slide9.xml'), ('firstFile', 'slide', 'slides/slide2.xml')])
        units, warnings = self.read(parts)
        self.assertTrue(units[0]['extraction_failed'])
        self.assertIn('Second displayed', units[-1]['text'])

    def test_multiple_notes_are_reported_without_arbitrary_selection(self):
        parts = basic_parts()
        parts['ppt/slides/_rels/slide9.xml.rels'] = relationships([
            ('n1', 'notesSlide', '../notesSlides/notesSlide8.xml'),
            ('n2', 'notesSlide', '../notesSlides/notesSlide8.xml')])
        units, warnings = self.read(parts)
        self.assertFalse(any(unit['kind'] == 'speaker_notes' for unit in units))
        self.assertTrue(any('多个备注关系' in warning for warning in warnings))

    def test_no_presentation_relationship_or_wrong_content_type_fails(self):
        for change in ('root', 'content', 'missing'):
            with self.subTest(change=change):
                parts = basic_parts()
                if change == 'root':
                    parts['_rels/.rels'] = relationships([('main', 'officeDocument', 'https://example.invalid/x', 'External')])
                elif change == 'content':
                    parts['[Content_Types].xml'] = parts['[Content_Types].xml'].replace(MAIN_TYPE, 'application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml')
                else:
                    del parts['ppt/_rels/presentation.xml.rels']
                with self.assertRaises(ValueError):
                    self.read(parts)

    def test_legacy_ppt_and_renamed_binary_get_conversion_guidance(self):
        self.path.with_suffix('.ppt').write_bytes(b'legacy')
        self.assertEqual(extract.run(self.path.with_suffix('.ppt'), self.root / 'old-output'), 2)
        entry = json.loads((self.root / 'old-output/manifest.json').read_text(encoding='utf-8'))['files'][0]
        self.assertEqual(entry['status'], 'unsupported')
        self.assertIn('不能只改后缀', entry['warnings'][0])
        self.path.write_bytes(b'legacy renamed to pptx')
        self.assertEqual(extract.run(self.path, self.root / 'bad-output'), 2)
        entry = json.loads((self.root / 'bad-output/manifest.json').read_text(encoding='utf-8'))['files'][0]
        self.assertEqual(entry['status'], 'failed')
        self.assertIn('另存为.pptx', entry['warnings'][0])

    def test_manifest_and_markdown_keep_slide_and_notes_metadata(self):
        mixed_pptx(self.path)
        output = self.root / 'output'
        self.assertEqual(extract.run(self.path, output), 0)
        entry = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))['files'][0]
        text = (output / 'sources.md').read_text(encoding='utf-8')
        self.assertEqual(entry['status'], 'extracted_with_warnings')
        self.assertEqual(len(entry['sha256']), 64)
        self.assertEqual(entry['units'][1]['id'], 'S001:n0001')
        self.assertEqual(entry['units'][1]['kind'], 'speaker_notes')
        self.assertTrue(entry['units'][-1]['hidden'])
        self.assertIn('第1页讲者备注', text)
        self.assertIn('第2页幻灯片（隐藏）', text)
        for unit in entry['units']:
            self.assertIn('### [' + unit['id'] + ']', text)

    def test_pptx_cli_works_with_ascii_console_and_non_ascii_path(self):
        path = self.root / '中文课件.PPTX'
        mixed_pptx(path)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/extract_sources.py'), str(path), '--out', str(self.root / '复习')],
                                capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'ascii'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['extracted'], 1)

    def test_path_traversal_in_archive_is_rejected_without_writing(self):
        for name in ('../outside.txt', '/absolute.txt', 'ppt/../../outside.txt', 'ppt\\evil.xml',
                     'ppt/evil\x00.xml', 'ppt//', 'C:/evil.xml'):
            with self.subTest(name=name):
                parts = basic_parts()
                parts[name] = 'never write me'
                write_pptx(self.path, parts, raw_names=True)
                with zipfile.ZipFile(self.path) as archive:
                    self.assertIn(name, [info.orig_filename for info in archive.infolist()])
                # Verify the unsafe name was really serialized in both ZIP
                # headers rather than normalized away by the fixture writer.
                self.assertEqual(self.path.read_bytes().count(name.encode('utf-8')), 2)
                with self.assertRaisesRegex(extract.PptxSafetyError, '路径'):
                    extract.pptx_units(self.path)
        self.assertFalse((self.root.parent / 'outside.txt').exists())

    def test_raw_backslash_member_survives_fixture_writing_on_windows(self):
        parts = basic_parts()
        raw_name = 'ppt\\evil.xml'
        parts[raw_name] = 'never write me'
        # Exercise ZipInfo's actual Windows sanitation path on every CI OS.
        with patch.object(zipfile.os, 'sep', '\\'), patch.object(zipfile.os, 'altsep', '/'):
            write_pptx(self.path, parts, raw_names=True)
            with zipfile.ZipFile(self.path) as archive:
                info = next(info for info in archive.infolist() if info.orig_filename == raw_name)
                self.assertEqual(info.filename, 'ppt/evil.xml')
                self.assertEqual(info.orig_filename, raw_name)
            with self.assertRaisesRegex(extract.PptxSafetyError, '路径'):
                extract.pptx_units(self.path)

    def test_raw_nul_member_is_rejected_before_zipinfo_truncation_hides_it(self):
        parts = basic_parts()
        raw_name = 'ppt/evil\x00.xml'
        parts[raw_name] = 'never write me'
        write_pptx(self.path, parts, raw_names=True)
        with zipfile.ZipFile(self.path) as archive:
            info = next(info for info in archive.infolist() if info.orig_filename == raw_name)
            self.assertEqual(info.filename, 'ppt/evil')
            self.assertEqual(info.orig_filename, raw_name)
        with self.assertRaisesRegex(extract.PptxSafetyError, '路径'):
            extract.pptx_units(self.path)

    def test_relationship_traversal_or_disguised_external_uri_fails_closed(self):
        for target in ('../../outside.xml', '/../../../outside.xml', '%2e%2e/%2e%2e/outside.xml',
                       'slides\\evil.xml', 'file:///etc/passwd', 'https://example.invalid/slide.xml', '//example.invalid/slide.xml'):
            with self.subTest(target=target):
                parts = basic_parts()
                parts['ppt/_rels/presentation.xml.rels'] = relationships([
                    ('secondFile', 'slide', target), ('firstFile', 'slide', 'slides/slide2.xml')])
                with self.assertRaises(extract.PptxSafetyError):
                    self.read(parts)

    def test_unsafe_notes_relationship_fails_whole_package_not_just_one_page(self):
        parts = basic_parts()
        parts['ppt/slides/_rels/slide9.xml.rels'] = relationships([('note', 'notesSlide', '../../../outside.xml')])
        with self.assertRaises(extract.PptxSafetyError):
            self.read(parts)

    def test_duplicate_zip_member_names_are_rejected(self):
        write_pptx(self.path)
        with python_warnings.catch_warnings():
            python_warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(self.path, 'a') as archive:
                archive.writestr('ppt/slides/slide2.xml', slide(shape('Ambiguous replacement')))
        with self.assertRaisesRegex(extract.PptxSafetyError, '重复成员'):
            extract.pptx_units(self.path)

    def test_zip_symlink_members_are_rejected(self):
        write_pptx(self.path)
        with zipfile.ZipFile(self.path, 'a') as archive:
            info = zipfile.ZipInfo('ppt/media/symlink')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '/outside')
        with self.assertRaisesRegex(extract.PptxSafetyError, '符号链接'):
            extract.pptx_units(self.path)

    def test_dtd_and_entities_are_rejected_in_utf8_and_utf16(self):
        for encoding in ('utf-8', 'utf-16'):
            with self.subTest(encoding=encoding):
                parts = basic_parts()
                parts['ppt/slides/slide9.xml'] = ('<?xml version="1.0" encoding="' + encoding + '"?>'
                    '<!DOCTYPE p:sld [<!ENTITY x "EXPANDED">]>' + slide(shape('Safe').replace('Safe', '&x;'))).encode(encoding)
                with self.assertRaisesRegex(extract.PptxSafetyError, 'DTD/实体'):
                    self.read(parts)

    def test_size_member_xml_node_and_slide_limits(self):
        for constant, value, term in (
            ('PPTX_MAX_ARCHIVE_BYTES', 1, '文件超过'),
            ('PPTX_MAX_EXPANDED_BYTES', 1, '解压后'),
            ('PPTX_MAX_MEMBERS', 1, '成员数量'),
            ('PPTX_MAX_XML_BYTES', 8, 'XML超过'),
            ('PPTX_MAX_XML_NODES', 1, '节点数量'),
            ('PPTX_MAX_XML_DEPTH', 1, '嵌套深度'),
            ('PPTX_MAX_SLIDES', 1, '幻灯片数量'),
        ):
            with self.subTest(constant=constant):
                write_pptx(self.path)
                with patch.object(extract, constant, value), self.assertRaisesRegex(ValueError, term):
                    extract.pptx_units(self.path)

    def test_high_compression_ratio_is_rejected_before_xml_read(self):
        parts = basic_parts()
        parts['ppt/media/repeated.bin'] = b'x' * (2 * 1024 * 1024)
        with self.assertRaisesRegex(extract.PptxSafetyError, '压缩比'):
            self.read(parts)

    def test_repeated_slide_and_notes_targets_have_cumulative_xml_budget(self):
        for repeated in ('slide', 'notes'):
            with self.subTest(repeated=repeated):
                parts = basic_parts()
                parts['ppt/presentation.xml'] = f'<p:presentation {NS}><p:sldIdLst>' + ''.join(
                    f'<p:sldId id="{256 + index}" r:id="secondFile"/>' for index in range(10)
                ) + '</p:sldIdLst></p:presentation>'
                if repeated == 'slide':
                    parts['ppt/slides/slide9.xml'] = slide(shape('x' * 10000))
                else:
                    parts['ppt/notesSlides/notesSlide8.xml'] = slide(shape('x' * 10000, placeholder='body'), notes=True)
                unique_size = sum(len(value) for value in parts.values())
                with patch.object(extract, 'PPTX_MAX_XML_READ_BYTES', unique_size + 100), \
                     self.assertRaisesRegex(extract.PptxSafetyError, '累计XML读取量'):
                    self.read(parts)

    def test_repeated_slide_and_notes_targets_have_cumulative_text_budget(self):
        for repeated in ('slide', 'notes'):
            with self.subTest(repeated=repeated):
                parts = basic_parts()
                parts['ppt/presentation.xml'] = f'<p:presentation {NS}><p:sldIdLst>' + ''.join(
                    f'<p:sldId id="{256 + index}" r:id="secondFile"/>' for index in range(3)
                ) + '</p:sldIdLst></p:presentation>'
                parts['ppt/slides/slide9.xml'] = slide(shape('x' * (1000 if repeated == 'slide' else 1)))
                parts['ppt/notesSlides/notesSlide8.xml'] = slide(
                    shape('y' * (1000 if repeated == 'notes' else 1), placeholder='body'), notes=True)
                write_pptx(self.path, parts)
                with patch.object(extract, 'PPTX_MAX_TEXT_CHARACTERS', 1500), \
                     self.assertRaisesRegex(extract.PptxSafetyError, '累计提取文字'):
                    extract.pptx_units(self.path)
                output = self.root / ('output-' + repeated)
                with patch.object(extract, 'PPTX_MAX_TEXT_CHARACTERS', 1500):
                    self.assertEqual(extract.run(self.path, output), 2)
                entry = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))['files'][0]
                self.assertEqual(entry['status'], 'failed')
                self.assertEqual(entry['units'], [])

    def test_notes_bad_relationships_and_unreadable_parts_warn(self):
        for name, value in (
            ('ppt/slides/_rels/slide9.xml.rels', '<broken'),
            ('ppt/notesSlides/notesSlide8.xml', '<broken'),
            ('ppt/notesSlides/_rels/notesSlide8.xml.rels', '<broken'),
        ):
            with self.subTest(name=name):
                parts = basic_parts()
                parts[name] = value
                units, warnings = self.read(parts)
                self.assertIn('First displayed', units[0]['text'])
                self.assertTrue(any('备注' in warning and ('失败' in warning or '缺失' in warning) for warning in warnings))

    def test_safety_failure_manifest_has_no_false_success_or_partial_text(self):
        parts = basic_parts()
        parts['ppt/slides/slide2.xml'] = '<!DOCTYPE x><x/>'
        write_pptx(self.path, parts)
        output = self.root / 'output'
        self.assertEqual(extract.run(self.path, output), 2)
        entry = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))['files'][0]
        self.assertEqual(entry['status'], 'failed')
        self.assertEqual(entry['units'], [])
        self.assertNotIn('First displayed', (output / 'sources.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
