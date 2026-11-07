import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quality_checker', ROOT / 'scripts/check_pack.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PackQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'pack'
        shutil.copytree(ROOT / 'examples/demo-output', self.root)
        self.manifest = self.root / '_sources/manifest.json'

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def assert_issue(self, text):
        issues = checker.check(self.root)
        self.assertTrue(any(text in issue for issue in issues), issues)

    def test_invalid_manifest_shapes_return_issues(self):
        for value in (None, [], {}, {'files': None}, {'files': {}}, {'files': [None]},
                      {'files': [{'units': None}]}, {'files': [{'units': [None]}]},
                      {'files': [{'units': [{'id': []}]}]}):
            with self.subTest(value=value):
                self.manifest.write_text(json.dumps(value), encoding='utf-8')
                self.assert_issue('无效来源清单')

    def test_invalid_manifest_json_and_encoding_return_issues(self):
        for content in (b'{bad', b'\xff'):
            with self.subTest(content=content):
                self.manifest.write_bytes(content)
                self.assert_issue('无效来源清单')

    def test_invalid_manifest_version_or_empty_units(self):
        original = json.loads(self.manifest.read_text(encoding='utf-8'))
        for version in (2, True, '1'):
            with self.subTest(version=version):
                data = {**original, 'schema_version': version}
                self.manifest.write_text(json.dumps(data), encoding='utf-8')
                self.assert_issue('schema_version')
        self.manifest.write_text('{"files": []}', encoding='utf-8')
        self.assert_issue('没有可引用')

    def test_duplicate_and_mismatched_manifest_ids(self):
        original = self.manifest.read_text(encoding='utf-8')
        for mutation, message in (
            (lambda data: data['files'].append(data['files'][0]), '重复来源'),
            (lambda data: data['files'][0]['units'].append(data['files'][0]['units'][0]), '重复引用'),
            (lambda data: data['files'][0]['units'][0].update(id='S002:p0001'), '与来源'),
            (lambda data: data['files'][0]['units'][0].update(id='S001:page1'), '格式无效'),
            (lambda data: data['files'][0]['units'][0].update(id='S001:p0000'), '格式无效'),
            (lambda data: data['files'][0].update(id=5), '格式无效'),
            (lambda data: data['files'][0].update(status='failed'), '不应包含'),
            (lambda data: data['files'][0].update(status=[]), '状态无效'),
        ):
            with self.subTest(message=message):
                data = json.loads(original)
                mutation(data)
                self.manifest.write_text(json.dumps(data), encoding='utf-8')
                self.assert_issue(message)

    def test_partial_manifest_can_include_unextracted_sources(self):
        data = json.loads(self.manifest.read_text(encoding='utf-8'))
        data['files'].append({'id': 'S003', 'status': 'unsupported', 'units': []})
        self.manifest.write_text(json.dumps(data), encoding='utf-8')
        self.assertEqual(checker.check(self.root), [])

    def test_manifest_symlink_is_not_followed(self):
        outside = Path(self.tmp.name) / 'outside.json'
        self.manifest.rename(outside)
        try:
            self.manifest.symlink_to(outside)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.assert_issue('符号链接')

    def test_required_directory_is_not_accepted_as_file(self):
        (self.root / '03-考前速查.md').unlink()
        (self.root / '03-考前速查.md').mkdir()
        self.assert_issue('缺少 03-考前速查.md')

    def test_bad_markdown_encoding_is_reported_without_abort(self):
        (self.root / '00-开始阅读.md').write_bytes(b'\xff')
        self.write('03-考前速查.md', '[S999:p0001]')
        self.assert_issue('无法读取 Markdown')
        self.assert_issue('无效引用')

    def test_empty_paper_and_answer_are_reported(self):
        self.write('练习卷/A-基础.md', ' \n\t')
        self.write('答案/A-解析.md', '')
        issues = checker.check(self.root)
        self.assertEqual(sum('没有正文' in issue for issue in issues), 2)

    def test_linked_paper_directory_is_not_counted_as_checked(self):
        directory = self.root / '练习卷'
        outside = Path(self.tmp.name) / 'papers'
        directory.rename(outside)
        try:
            directory.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.assert_issue('不检查符号链接目录')

    def test_invalid_public_check_options_are_reported(self):
        for mode, papers in (('invalid', 3), ('both', 0), ('both', True), ('both', '3')):
            with self.subTest(mode=mode, papers=papers):
                self.assertTrue(checker.check(self.root, mode, papers))

    def test_code_and_comment_citations_do_not_count(self):
        for text in ('`[S001:p0001]`', '```text\n[S001:p0001]\n```',
                     '~~~\n[S001:p0001]\n~~~', '<!-- [S001:p0001] -->', r'\[S001:p0001]'):
            with self.subTest(text=text):
                self.write('02-详细复习.md', text)
                self.assert_issue('没有来源引用')

    def test_invalid_citations_inside_code_are_not_reported(self):
        self.write('02-详细复习.md', '[S001:p0001]\n`[S999:p0001]`\n<!-- [S998:p0001] -->')
        self.assertEqual(checker.check(self.root), [])

    def test_malformed_source_like_citation_is_reported(self):
        self.write('02-详细复习.md', '[S001:p0001] [S001:page1]')
        self.assert_issue('无效引用 S001:page1')

    def test_nested_backtick_run_does_not_expose_code_examples(self):
        self.write('00-开始阅读.md', '`` a ` [link](missing.md) [S999:p0001] ``')
        self.assertEqual(checker.check(self.root), [])

    def test_fence_requires_valid_closing_line(self):
        self.write('00-开始阅读.md', '```markdown\n```not-a-closing-fence\n[x](missing.md)\n```')
        self.assertEqual(checker.check(self.root), [])

    def test_comments_and_escaped_or_incomplete_links_are_ignored(self):
        self.write('00-开始阅读.md', '<!-- [x](missing.md) -->\n\\[literal](missing.md)\n[x](not-closed.md\n](not-a-link.md)')
        self.assertEqual(checker.check(self.root), [])

    def test_reference_links_images_collapsed_and_shortcut(self):
        self.write('00-开始阅读.md', '[map][Guide] ![image][picture] [collapsed][] [shortcut]\n\n'
                   '[guide]: 01-知识地图.md "Title"\n[picture]: 03-考前速查.md\n'
                   '[collapsed]: 04-覆盖与待核对.md\n[shortcut]: 02-详细复习.md\n')
        self.assertEqual(checker.check(self.root), [])
        self.write('00-开始阅读.md', '![image][picture]\n[picture]: missing.png\n')
        self.assert_issue('目标不存在 missing.png')

    def test_reference_destination_can_contain_escaped_parentheses_or_spaces(self):
        self.write('附加/函数(上) 笔记.md', '补充')
        self.write('00-开始阅读.md', '[x][a]\n[a]: <附加/函数(上) 笔记.md> "说明"\n')
        self.assertEqual(checker.check(self.root), [])
        self.write('附加/函数(上).md', '补充')
        self.write('00-开始阅读.md', r'[x](附加/函数\(上\).md)' + '\n')
        self.assertEqual(checker.check(self.root), [])

    def test_reference_label_case_and_whitespace_normalization(self):
        self.write('00-开始阅读.md', '[x][Some   Guide]\n[some guide]: 01-知识地图.md\n')
        self.assertEqual(checker.check(self.root), [])
        self.assertEqual(list(checker.markdown_targets('[x][Some   Guide]\n[some guide]: missing.md')), ['missing.md'])

    def test_linked_image_checks_both_destinations(self):
        self.write('00-开始阅读.md', '[![preview](missing.png)](01-知识地图.md)')
        self.assert_issue('目标不存在 missing.png')
        self.write('00-开始阅读.md', '[![preview](missing.png)](missing.md)')
        self.assert_issue('目标不存在 missing.png')
        self.assert_issue('目标不存在 missing.md')
        self.write('preview.png', 'image placeholder')
        self.write('00-开始阅读.md', '[![preview](preview.png)](01-知识地图.md)')
        self.assertEqual(checker.check(self.root), [])

    def test_linked_reference_images_share_reference_definitions(self):
        for image in ('![preview][image]', '![image][]', '![image]'):
            with self.subTest(image=image):
                self.write('00-开始阅读.md', '[' + image + '][guide]\n'
                           '[image]: missing.png\n[guide]: 01-知识地图.md\n')
                self.assert_issue('目标不存在 missing.png')

    def test_comment_openers_inside_code_do_not_hide_real_links(self):
        for code in ('`<!--`', '`` literal ` <!-- ``'):
            with self.subTest(code=code):
                self.write('00-开始阅读.md', code + ' [x](missing.md)')
                self.assert_issue('目标不存在 missing.md')
        self.write('02-详细复习.md', '`<!--` [S999:p0001]')
        self.assert_issue('无效引用 S999:p0001')

    def test_backticks_inside_comments_do_not_hide_real_links(self):
        self.write('00-开始阅读.md', '<!-- ` --> [x](missing.md) `')
        self.assert_issue('目标不存在 missing.md')

    def test_code_spans_cannot_cross_blank_paragraph_boundaries(self):
        for blank in ('\n\n', '\n  \n', '\r\n\t\r\n'):
            with self.subTest(blank=blank):
                self.write('00-开始阅读.md', '`literal' + blank + '[x](missing.md)' + blank + 'other `')
                self.assert_issue('目标不存在 missing.md')

    def test_multiline_code_in_one_paragraph_still_ignores_links(self):
        self.write('00-开始阅读.md', '`literal\n[x](missing.md)\nother`')
        self.assertEqual(checker.check(self.root), [])

    def test_real_comments_can_cross_blank_paragraph_boundaries(self):
        self.write('00-开始阅读.md', '<!-- start\n\n[x](missing.md)\n\nend -->')
        self.assertEqual(checker.check(self.root), [])

    def test_unused_reference_definitions_are_not_links(self):
        self.write('00-开始阅读.md', '正文\n[unused]: missing.md\n')
        self.assertEqual(checker.check(self.root), [])

    def test_reference_navigation_is_recognized(self):
        self.write('章节/第一章.md', '内容 [S001:p0001]')
        self.write('02-详细复习.md', '[第一章][chapter]\n[chapter]: 章节/第一章.md\n')
        self.assertEqual(checker.check(self.root), [])

    def test_percent_encoding_query_fragment_and_html_entities(self):
        self.write('附加/例题 #1&2.md', '说明')
        self.write('00-开始阅读.md', '[x](附加/例题%20%231&amp;2.md?view=1#part)')
        self.assertEqual(checker.check(self.root), [])
        self.write('00-开始阅读.md', '[x](%2e%2e/outside.md)')
        self.assert_issue('越出复习包')

    def test_external_doi_email_and_fragment_links_do_not_fetch(self):
        self.write('00-开始阅读.md', '[web](https://example.invalid/a) [DOI](doi:10.1000/182) '
                   '[email](mailto:example@example.invalid) [anchor](#section)')
        self.assertEqual(checker.check(self.root), [])

    def test_malformed_uri_does_not_abort_remaining_checks(self):
        self.write('00-开始阅读.md', '[broken](http://[bad) [local](missing.md)')
        self.assert_issue('无效链接 http://[bad')
        self.assert_issue('目标不存在 missing.md')

    def test_missing_and_extra_answer_heading_ids(self):
        path = self.root / '答案/A-解析.md'
        original = path.read_text(encoding='utf-8')
        self.write('答案/A-解析.md', original.replace('## A3', '## A4'))
        self.assert_issue('题答编号不一一对应')
        self.assert_issue("缺少答案 ['A3']")
        self.assert_issue("多余答案 ['A4']")

    def test_duplicate_question_or_answer_heading_ids(self):
        self.write('练习卷/A-基础.md', '# 练习 A\n## A1（5分）\n问题\n## A1（5分）\n另一问题')
        self.write('答案/A-解析.md', '# 答案 A\n## A1\n答案\n## A1\n另一答案')
        issues = checker.check(self.root)
        self.assertEqual(sum('重复题号' in issue for issue in issues), 2)

    def test_diverse_explicit_question_heading_formats(self):
        formats = [
            ('## **A1**（5分）\n问题\n### A2: 问题', '## A1\n答案\n## **A2**\n答案'),
            ('## 第1题（5分）\n问题\n## 第2题\n问题', '## 1. 解答\n答案\n## 2、解答\n答案'),
            ('## 题目1\n问题\n## Question 2\n问题', '## 第1题\n答案\n## 第2题\n答案'),
        ]
        for paper, answer in formats:
            with self.subTest(paper=paper):
                self.write('练习卷/A-基础.md', paper)
                self.write('答案/A-解析.md', answer)
                self.assertEqual(checker.check(self.root), [])

    def test_decimal_question_ids_are_not_truncated(self):
        self.write('练习卷/A-基础.md', '## 1.1 问题\n正文\n## 1.2 问题\n正文')
        self.write('答案/A-解析.md', '## 1.1 答案\n正文\n## 1.2 答案\n正文')
        self.assertEqual(checker.check(self.root), [])
        self.write('答案/A-解析.md', '## 1.1 答案\n正文')
        self.assert_issue("缺少答案 ['1.2']")

    def test_letter_subparts_are_not_collapsed_into_duplicate_ids(self):
        self.write('练习卷/A-基础.md', '## A1(a)\n问题\n## A1(b)\n问题')
        self.write('答案/A-解析.md', '## A1（a）\n答案\n## A1（b）\n答案')
        self.assertEqual(checker.check(self.root), [])

    def test_nested_section_numbering_is_left_for_manual_review(self):
        self.write('练习卷/A-基础.md', '## 1. 选择题\n### 1. 问题\n### 2. 问题')
        self.write('答案/A-解析.md', '## 1. 选择题\n### 1. 解答\n### 2. 解答')
        self.assertEqual(checker.check(self.root), [])

    def test_numeric_question_ids_detect_missing_answer(self):
        self.write('练习卷/A-基础.md', '## 第1题\n问题\n## 第2题\n问题')
        self.write('答案/A-解析.md', '## 1. 解答\n答案')
        self.assert_issue('题答编号不一一对应')

    def test_question_heading_examples_in_code_are_ignored(self):
        path = self.root / '答案/A-解析.md'
        self.write('答案/A-解析.md', path.read_text(encoding='utf-8') + '\n```markdown\n## A1\n```')
        self.assertEqual(checker.check(self.root), [])

    def test_unrecognized_prose_numbering_is_left_for_manual_review(self):
        self.write('练习卷/A-基础.md', '第一题：说明算法。\n第二题：说明边界。')
        self.write('答案/A-解析.md', '一、算法说明。\n二、边界说明。')
        self.assertEqual(checker.check(self.root), [])

    def test_hyphenless_matching_paper_basename(self):
        (self.root / '练习卷/A-基础.md').rename(self.root / '练习卷/A.md')
        self.write('00-开始阅读.md', '索引')
        self.assertEqual(checker.check(self.root), [])

    def test_cli_invalid_manifest_is_machine_readable_with_ascii_console(self):
        self.manifest.write_text('{bad', encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_pack.py'), str(self.root)],
                                capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'ascii'})
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['pass'])
        self.assertIn('无效来源清单', report['issues'][0])
        self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
