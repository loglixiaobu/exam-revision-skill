import importlib.util
import shutil
import json
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('checker', ROOT/'scripts/check_pack.py')
checker = importlib.util.module_from_spec(spec); spec.loader.exec_module(checker)

class PackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'pack'
        shutil.copytree(ROOT/'examples/demo-output', self.root)
    def tearDown(self): self.tmp.cleanup()
    def test_modes_and_count(self):
        self.assertEqual(checker.check(self.root, 'both', 3), [])
        (self.root/'02-精简复习.md').unlink()
        self.assertTrue(any('模式' in e for e in checker.check(self.root,'both',3)))
        self.assertTrue(any('数量' in e for e in checker.check(self.root,'detailed',4)))
    def test_missing_link_and_escape(self):
        (self.root/'00-开始阅读.md').write_text('[缺失](missing.md) [外部](../outside.md)',encoding='utf-8')
        errors=checker.check(self.root)
        self.assertTrue(any('不存在' in e for e in errors)); self.assertTrue(any('越出' in e for e in errors))
    def test_chapter_navigation(self):
        (self.root/'章节').mkdir()
        (self.root/'章节/01.md').write_text('解释 [S001:p0001]',encoding='utf-8')
        (self.root/'02-详细复习.md').write_text('[第一章](章节/01.md)',encoding='utf-8')
        self.assertEqual(checker.check(self.root),[])
        (self.root/'章节/01.md').write_text('无出处',encoding='utf-8')
        self.assertTrue(any('没有来源' in e for e in checker.check(self.root)))
    def test_balanced_link_and_title(self):
        (self.root/'章节').mkdir()
        (self.root/'章节/01-函数(上).md').write_text('解释 [S001:p0001]',encoding='utf-8')
        (self.root/'02-详细复习.md').write_text('[函数上册](章节/01-函数(上).md) [图](01-知识地图.md "导航")',encoding='utf-8')
        self.assertEqual(checker.check(self.root),[])
    def test_links_in_code_ignored(self):
        (self.root/'00-开始阅读.md').write_text('`[例子](missing.md)`\n```markdown\n[x](no.md)\n```',encoding='utf-8')
        self.assertEqual(checker.check(self.root),[])
    def test_saved_settings_default(self):
        (self.root/'_session').mkdir()
        (self.root/'_session/state.json').write_text(json.dumps({'settings':{'mode':'both','papers':3}}))
        (self.root/'02-精简复习.md').unlink()
        self.assertTrue(any('模式' in e for e in checker.check(self.root)))
        # Explicit flags select what to validate, including exported subsets.
        self.assertFalse(any('模式' in e for e in checker.check(self.root,'detailed',3)))
    def test_bad_saved_settings(self):
        (self.root/'_session').mkdir()
        (self.root/'_session/state.json').write_text('{broken')
        self.assertTrue(any('已保存' in e for e in checker.check(self.root)))
    def test_duplicate_papers(self):
        (self.root/'练习卷/A-重复.md').write_text('题目',encoding='utf-8')
        self.assertTrue(any('重复' in e for e in checker.check(self.root)))

if __name__=='__main__': unittest.main()
