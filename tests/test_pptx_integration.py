"""PPTX citation compatibility with existing packs and installed workflows."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pptx_checker', ROOT / 'scripts/check_pack.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PptxCitationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pack = Path(self.temp.name) / 'pack'
        shutil.copytree(ROOT / 'examples/demo-output', self.pack)
        self.manifest = self.pack / '_sources/manifest.json'
        data = json.loads(self.manifest.read_text(encoding='utf-8'))
        data['files'].append({'id': 'S003', 'file': 'slides.pptx', 'status': 'extracted_with_warnings',
                              'units': [{'id': 'S003:s0001', 'kind': 'slide'},
                                        {'id': 'S003:n0001', 'kind': 'speaker_notes'}]})
        self.manifest.write_text(json.dumps(data), encoding='utf-8')

    def cite(self, text):
        p = self.pack / '02-详细复习.md'
        p.write_text(p.read_text(encoding='utf-8') + '\n' + text, encoding='utf-8')

    def test_slide_and_notes_citations_coexist_with_pdf_docx(self):
        self.cite('幻灯片 [S003:s0001]；讲者备注 [S003:n0001]。')
        self.assertEqual(checker.check(self.pack, 'both', 3), [])

    def test_missing_notes_citation_is_rejected(self):
        self.cite('讲者备注 [S003:n0002]。')
        self.assertTrue(any('S003:n0002' in x for x in checker.check(self.pack)))

    def test_slide_zero_is_rejected_in_manifest(self):
        data = json.loads(self.manifest.read_text(encoding='utf-8'))
        data['files'][-1]['units'][0]['id'] = 'S003:s0000'
        self.manifest.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('引用 ID 格式无效' in x for x in checker.check(self.pack)))

    def test_notes_wrong_source_is_rejected(self):
        data = json.loads(self.manifest.read_text(encoding='utf-8'))
        data['files'][-1]['units'][1]['id'] = 'S004:n0001'
        self.manifest.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('不一致' in x for x in checker.check(self.pack)))


class InstalledPptxWorkflowTests(unittest.TestCase):
    def test_installed_extraction_checkpoints_and_change_detection(self):
        fixture_spec = importlib.util.spec_from_file_location('pptx_fixture_integration', ROOT / 'tests/fixtures/pptx_sources.py')
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / '课程 project'
            project.mkdir()
            inputs = root / 'inputs'
            inputs.mkdir()
            deck = inputs / 'lesson.pptx'
            fixture.mixed_pptx(deck)
            pack = root / 'pack'

            def run(script, *args, expected=0):
                result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return result

            run(ROOT / 'scripts/install.py', '--project', project, '--install')
            runtime = project / '.agents/skills/exam-revision/scripts'
            run(runtime / 'session.py', 'init', inputs, '--out', pack, '--mode', 'both', '--papers', '3')
            run(runtime / 'extract_sources.py', inputs, '--out', pack / '_sources')
            manifest = json.loads((pack / '_sources/manifest.json').read_text(encoding='utf-8'))
            units = manifest['files'][0]['units']
            self.assertTrue(any(u['id'] == 'S001:s0001' for u in units))
            self.assertTrue(any(u['id'] == 'S001:n0001' for u in units))
            run(runtime / 'session.py', 'record', pack, '--phase', 'extract', '--key', 'pptx', '--file', '_sources/manifest.json', '--file', '_sources/sources.md', '--complete-phase')
            state = (pack / '_session/state.json').read_bytes()
            status = json.loads(run(runtime / 'session.py', 'status', pack).stdout)
            self.assertEqual(status['settings'], {'mode': 'both', 'papers': 3})
            self.assertEqual(status['next_phase'], 'inventory')
            self.assertEqual(state, (pack / '_session/state.json').read_bytes())
            deck.write_bytes(deck.read_bytes() + b'changed')
            run(runtime / 'session.py', 'status', pack, expected=2)
            self.assertEqual(state, (pack / '_session/state.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
