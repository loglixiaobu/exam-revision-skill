"""End-to-end restart, user-edit, and commit-boundary regressions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('session_quality', ROOT / 'scripts/session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class SessionQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / '课程资料'
        self.source.mkdir()
        self.course = self.source / '第一章.pdf'
        self.course.write_bytes(b'original chapter')
        self.pack = self.root / '复习包'

    @property
    def state_path(self):
        return self.pack / '_session/state.json'

    def init(self):
        return session.init(self.source, self.pack, mode='both', papers=5)

    def output(self, name, content='Reviewed chapter\n'):
        path = self.pack / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return name

    def cli(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/session.py'), *map(str, args)],
            capture_output=True, text=True, encoding='utf-8', timeout=10)
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        self.assertNotIn('Traceback', result.stderr)
        return json.loads(result.stdout if result.stdout else result.stderr)

    def test_complete_course_survives_separate_process_restarts(self):
        self.cli('init', self.source, '--out', self.pack, '--mode', 'both', '--papers', '5')
        for index, phase in enumerate(session.PHASES):
            name = self.output(f'{phase}/reviewed.md')
            self.cli('record', self.pack, '--phase', phase, '--key', 'reviewed', '--file', name)
            pending = self.cli('status', self.pack)
            self.assertEqual(pending['next_phase'], phase)
            self.assertEqual(pending['settings'], {'mode': 'both', 'papers': 5})
            complete = self.cli('record', self.pack, '--phase', phase, '--key', 'reviewed',
                                '--file', name, '--complete-phase')
            self.assertEqual(complete['completed_phases'], list(session.PHASES[:index + 1]))
        original = self.state_path.read_bytes()
        resumed = self.cli('init', self.source, '--out', self.pack)
        self.assertIsNone(resumed['next_phase'])
        self.assertEqual(resumed['pending_phases'], [])
        self.assertEqual(resumed['revision'], 2 * len(session.PHASES))
        self.assertEqual(resumed['settings'], {'mode': 'both', 'papers': 5})
        self.assertFalse(resumed['created'])
        self.assertEqual(self.state_path.read_bytes(), original)
        personal = self.output('我的笔记.md', '用户自己的笔记，不要覆盖。')
        review = self.cli('status', self.pack)
        self.assertTrue(review['needs_review'])
        self.assertEqual(review['unrecorded_files'], [personal])
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_new_course_cannot_reuse_completed_pack_or_settings(self):
        self.init()
        name = self.output('notes.md')
        session.record(self.pack, 'notes', 'ch01', [name], complete_phase=True)
        saved = self.state_path.read_bytes()
        second_course = self.root / '其他课程'
        second_course.mkdir()
        (second_course / '第一章.pdf').write_bytes(b'other course')
        with self.assertRaisesRegex(session.SessionError, 'different input'):
            session.init(second_course, self.pack)
        self.assertEqual(saved, self.state_path.read_bytes())
        fresh = session.init(second_course, self.root / '新复习包', mode='concise', papers=2)
        self.assertEqual(fresh['settings'], {'mode': 'concise', 'papers': 2})
        self.assertEqual(fresh['checkpoints'], [])
        self.assertEqual(fresh['next_phase'], 'extract')

    def test_preserved_annotations_and_unregistered_drafts_survive_restarts(self):
        self.init()
        first = self.output('notes/ch01.md')
        session.record(self.pack, 'notes', 'ch01', [first])
        original_checkpoint = json.loads(self.state_path.read_text(encoding='utf-8'))['checkpoints'][0]
        self.output(first, 'My annotations remain here.')
        draft = self.output('notes/interrupted.md', 'unfinished draft')
        second = self.output('notes/ch02.md')
        result = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch02',
                          '--file', second, '--preserve-edits', expected=2)
        self.assertTrue(result['recorded'])
        self.assertEqual(result['preserved_output_edits'], [first])
        saved = self.state_path.read_bytes()
        repeated = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch02',
                            '--file', second, '--preserve-edits', expected=2)
        self.assertFalse(repeated['recorded'])
        self.assertEqual(saved, self.state_path.read_bytes())
        resumed = self.cli('init', self.source, '--out', self.pack, expected=2)
        self.assertEqual(resumed['settings'], {'mode': 'both', 'papers': 5})
        self.assertEqual(resumed['unrecorded_files'], [draft])
        self.assertEqual(resumed['output_changes']['changed'], [first])
        self.assertEqual(json.loads(saved)['checkpoints'][0], original_checkpoint)
        self.assertEqual((self.pack / first).read_text(encoding='utf-8'), 'My annotations remain here.')
        self.assertEqual((self.pack / draft).read_text(encoding='utf-8'), 'unfinished draft')

    def test_new_input_blocks_preserve_edits_without_rebaselining(self):
        self.init()
        first = self.output('notes/ch01.md')
        session.record(self.pack, 'notes', 'ch01', [first])
        self.output(first, 'User annotations')
        second = self.output('notes/ch02.md')
        (self.source / '新增课件.pdf').write_bytes(b'new chapter')
        saved = self.state_path.read_bytes()
        result = self.cli('status', self.pack, expected=2)
        self.assertEqual(result['input_changes']['added'], ['新增课件.pdf'])
        self.assertFalse(result['can_continue_with_preserved_edits'])
        self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch02',
                 '--file', second, '--preserve-edits', expected=1)
        self.assertEqual(saved, self.state_path.read_bytes())

    def test_bookkeeping_case_and_windows_trim_aliases_are_not_content(self):
        self.init()
        saved = self.state_path.read_bytes()
        for prefix in ('_SESSION', '_Session', '_session.', '_session ', '_SESSION. '):
            with self.subTest(prefix=prefix):
                with self.assertRaisesRegex(session.SessionError, 'bookkeeping'):
                    session._relative(prefix + '/state.json')
                with self.assertRaisesRegex(session.SessionError, 'bookkeeping'):
                    session.record(self.pack, 'notes', 'state', [prefix + '/state.json'])
        self.assertEqual(saved, self.state_path.read_bytes())
        self.assertEqual(session._relative('notes/_session.md'), 'notes/_session.md')

    @unittest.skipUnless(os.name == 'nt', 'Windows case-insensitive path regression')
    def test_windows_bookkeeping_alias_cannot_be_registered(self):
        self.init()
        saved = self.state_path.read_bytes()
        self.assertTrue((self.pack / '_SESSION/state.json').is_file())
        self.cli('record', self.pack, '--phase', 'notes', '--key', 'state',
                 '--file', '_SESSION/state.json', expected=1)
        self.assertEqual(saved, self.state_path.read_bytes())
        self.assertTrue(session.status(self.pack)['ok'])

    def mutate_after_hash(self, target, occurrence, action):
        original = session._hash_file
        count = 0

        def hashed(path):
            nonlocal count
            result = original(path)
            if path == target:
                count += 1
                if count == occurrence:
                    action()
            return result

        return patch.object(session, '_hash_file', side_effect=hashed)

    def test_source_change_during_init_does_not_save_stale_baseline(self):
        with self.mutate_after_hash(self.course, 1, lambda: self.course.write_bytes(b'new source')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                self.init()
        self.assertFalse(self.state_path.exists())
        self.assertTrue(self.init()['ok'])
        self.assertTrue(session.status(self.pack)['ok'])

    def test_source_change_during_record_does_not_complete_phase(self):
        self.init()
        name = self.output('notes.md')
        saved = self.state_path.read_bytes()
        # First output read is the initial integrity scan; second is evidence.
        with self.mutate_after_hash(self.pack / name, 2,
                                    lambda: self.course.write_bytes(b'new source')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch01', [name], complete_phase=True)
        self.assertEqual(saved, self.state_path.read_bytes())
        result = session.status(self.pack)
        self.assertEqual(result['completed_phases'], [])
        self.assertEqual(result['input_changes']['changed'], [self.course.name])
        self.assertEqual(result['unrecorded_files'], [name])

    def test_new_evidence_changed_after_hash_is_not_committed(self):
        self.init()
        name = self.output('notes.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / name, 2,
                                    lambda: self.output(name, 'New user edits')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch01', [name])
        self.assertEqual(saved, self.state_path.read_bytes())
        self.assertEqual((self.pack / name).read_text(encoding='utf-8'), 'New user edits')
        self.assertEqual(session.status(self.pack)['checkpoints'], [])

    def test_new_evidence_removed_after_hash_is_not_committed(self):
        self.init()
        name = self.output('notes.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / name, 2, lambda: (self.pack / name).unlink()):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch01', [name])
        self.assertEqual(saved, self.state_path.read_bytes())
        self.assertEqual(session.status(self.pack)['checkpoints'], [])

    def test_preserve_edits_does_not_hide_new_commit_time_conflicts(self):
        self.init()
        first = self.output('notes/ch01.md')
        session.record(self.pack, 'notes', 'ch01', [first])
        self.output(first, 'My annotations')
        second = self.output('notes/ch02.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / second, 2,
                                    lambda: self.output(second, 'Unreviewed new version')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertEqual(saved, self.state_path.read_bytes())
        result = session.status(self.pack)
        self.assertEqual(result['output_changes']['changed'], [first])
        self.assertEqual(result['unrecorded_files'], [second])

    def test_preserve_edits_does_not_hide_commit_time_source_change(self):
        self.init()
        first = self.output('notes/ch01.md')
        session.record(self.pack, 'notes', 'ch01', [first])
        self.output(first, 'My annotations')
        second = self.output('notes/ch02.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / second, 2,
                                    lambda: self.course.write_bytes(b'new source version')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertEqual(saved, self.state_path.read_bytes())
        result = session.status(self.pack)
        self.assertEqual(result['input_changes']['changed'], [self.course.name])
        self.assertFalse(result['can_continue_with_preserved_edits'])

    def test_preserve_edits_does_not_hide_new_conflict_in_other_tracked_file(self):
        self.init()
        first = self.output('notes/ch01.md')
        untouched = self.output('notes/references.md')
        session.record(self.pack, 'notes', 'ch01', [first, untouched])
        self.output(first, 'My annotations')
        second = self.output('notes/ch02.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / second, 2,
                                    lambda: self.output(untouched, 'Unexpected reference edit')):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertEqual(saved, self.state_path.read_bytes())
        result = session.status(self.pack)
        self.assertEqual(result['output_changes']['changed'], sorted([first, untouched]))
        self.assertEqual(result['unrecorded_files'], [second])

    def test_final_scan_rejects_missing_previously_preserved_output(self):
        self.init()
        first = self.output('notes/ch01.md')
        session.record(self.pack, 'notes', 'ch01', [first])
        self.output(first, 'My annotations')
        second = self.output('notes/ch02.md')
        saved = self.state_path.read_bytes()
        with self.mutate_after_hash(self.pack / second, 2, lambda: (self.pack / first).unlink()):
            with self.assertRaisesRegex(session.SessionError, 'changed|integrity'):
                session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertEqual(saved, self.state_path.read_bytes())
        self.assertEqual(session.status(self.pack)['output_changes']['missing'], [first])


if __name__ == '__main__':
    unittest.main()
