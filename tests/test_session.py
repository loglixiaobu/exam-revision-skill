import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('session', ROOT / 'scripts/session.py')
session = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(session)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'inputs'
        self.source.mkdir()
        (self.source / '01.pdf').write_bytes(b'original course bytes')
        (self.source / '02.docx').write_bytes(b'other course bytes')
        self.pack = self.root / 'pack'

    @property
    def state_path(self):
        return self.pack / '_session/state.json'

    def init(self):
        return session.init(self.source, self.pack)

    def write_output(self, name='chapters/ch01.md', content='# Chapter 1\nReviewed material.\n'):
        path = self.pack / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return name

    def record(self, name='chapters/ch01.md', key='ch01', phase='notes', complete=False):
        return session.record(self.pack, phase, key, [name], complete)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/session.py'), *map(str, args)],
                              capture_output=True, text=True, encoding='utf-8', timeout=10)

    def symlink(self, link, target, is_directory=False):
        try:
            link.symlink_to(target, target_is_directory=is_directory)
        except OSError as exc:
            if os.name == 'nt' and getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows account lacks symlink creation privilege')
            raise

    def test_init_tracks_all_inputs_and_creates_no_content(self):
        result = self.init()
        self.assertTrue(result['ok'])
        self.assertTrue(result['created'])
        self.assertEqual(result['next_phase'], 'extract')
        self.assertEqual(result['unrecorded_files'], [])
        self.assertEqual([p.name for p in self.pack.iterdir()], ['_session'])
        data = json.loads(self.state_path.read_text())
        self.assertEqual(set(data['source']['files']), {'01.pdf', '02.docx'})
        self.assertEqual(len(data['source']['files']['01.pdf']['sha256']), 64)

    def stat_copy(self, info, **changes):
        values = {name: getattr(info, name) for name in
                  ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        values.update(changes)
        return SimpleNamespace(**values)

    def test_hash_accepts_different_handle_and_path_metadata(self):
        path = self.source / '01.pdf'
        info = path.lstat()
        # Model Windows API differences: fstat may expose different IDs and
        # lower timestamp precision. They are stable within the same API.
        descriptor = self.stat_copy(
            info, st_dev=info.st_dev + 1, st_ino=info.st_ino + 1,
            st_mtime_ns=info.st_mtime_ns // 1_000_000_000 * 1_000_000_000,
            st_ctime_ns=info.st_ctime_ns // 1_000_000_000 * 1_000_000_000)
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.object(session.os, 'fstat', return_value=descriptor) as fstat:
            result = session._hash_file(path)
        self.assertEqual(result, {'sha256': expected, 'size': info.st_size})
        self.assertEqual(fstat.call_count, 3)

    def test_hash_rejects_file_modified_during_read(self):
        path = self.source / '01.pdf'
        before = path.stat()
        digest = hashlib.sha256()
        changed = False

        def update_and_modify(chunk):
            nonlocal changed
            digest.update(chunk)
            if not changed:
                changed = True
                path.write_bytes(b'X' * before.st_size)
                # Explicitly advance mtime so the regression does not depend
                # on OS clock/filesystem timestamp granularity.
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))

        wrapper = SimpleNamespace(update=update_and_modify, hexdigest=digest.hexdigest)
        with patch.object(session.hashlib, 'sha256', return_value=wrapper):
            with self.assertRaisesRegex(session.SessionError, 'changed while being read'):
                session._hash_file(path)

    def test_hash_rejects_handle_metadata_changes(self):
        path = self.source / '01.pdf'
        before = path.lstat()
        after = self.stat_copy(before, st_mtime_ns=before.st_mtime_ns + 100)
        with patch.object(session.os, 'fstat', side_effect=[before, after]):
            with self.assertRaisesRegex(session.SessionError, 'changed while being read'):
                session._hash_file(path)

    def test_hash_rejects_reopened_handle_identity_change(self):
        path = self.source / '01.pdf'
        before = path.lstat()
        replaced = self.stat_copy(before, st_ino=before.st_ino + 1)
        with patch.object(session.os, 'fstat', side_effect=[before, before, replaced]):
            with self.assertRaisesRegex(session.SessionError, 'changed while being read'):
                session._hash_file(path)

    def test_hash_rejects_path_change_even_if_handle_metadata_is_coarse(self):
        path = self.source / '01.pdf'
        before = path.lstat()
        changed = self.stat_copy(before, st_mtime_ns=before.st_mtime_ns + 100)
        original_lstat = Path.lstat
        with patch.object(session.os, 'fstat', return_value=before) as fstat:
            def lstat_after_read(candidate):
                if candidate == path and fstat.call_count >= 2:
                    return changed
                return original_lstat(candidate)

            with patch.object(Path, 'lstat', lstat_after_read):
                with self.assertRaisesRegex(session.SessionError, 'changed while being read'):
                    session._hash_file(path)

    def test_single_file_input(self):
        result = session.init(self.source / '01.pdf', self.pack)
        self.assertTrue(result['ok'])
        self.assertTrue(session.status(self.pack)['ok'])
        (self.source / '02.docx').write_text('unrelated')
        self.assertTrue(session.status(self.pack)['ok'])

    def test_only_input_housekeeping_is_ignored(self):
        ignored = ['~$lecture.docx', '.DS_Store', 'Thumbs.db', 'DESKTOP.INI']
        for name in ignored:
            (self.source / name).write_bytes(b'housekeeping')
        self.init()
        data = json.loads(self.state_path.read_text())
        self.assertEqual(set(data['source']['files']), {'01.pdf', '02.docx'})
        for name in ignored:
            (self.source / name).unlink()
        self.assertTrue(session.status(self.pack)['ok'])
        for name in ignored:
            (self.source / name).write_bytes(b'new temporary bytes')
        self.assertTrue(session.status(self.pack)['ok'])
        self.write_output('.DS_Store', 'Do not silently ignore output content')
        self.assertIn('.DS_Store', session.status(self.pack)['unrecorded_files'])

    def test_housekeeping_only_input_is_rejected(self):
        empty = self.root / 'empty'
        empty.mkdir()
        (empty / '~$temp.docx').write_text('Not course material')
        with self.assertRaisesRegex(session.SessionError, 'no regular course files'):
            session.init(empty, self.pack)

    def test_repeated_init_is_byte_identical(self):
        self.init()
        before = self.state_path.read_bytes()
        result = self.init()
        self.assertFalse(result['created'])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_mode_and_paper_settings_persist_across_resume(self):
        result = session.init(self.source, self.pack, mode='both', papers=5)
        self.assertEqual(result['settings'], {'mode': 'both', 'papers': 5})
        self.assertEqual(self.init()['settings'], result['settings'])
        self.assertEqual(session.status(self.pack)['settings'], result['settings'])
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(session.SessionError, 'settings differ'):
            session.init(self.source, self.pack, mode='concise')
        with self.assertRaisesRegex(session.SessionError, 'settings differ'):
            session.init(self.source, self.pack, papers=3)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_invalid_settings_are_rejected(self):
        for mode, papers in [('unknown', None), (None, 0), (None, -1), (None, True)]:
            with self.subTest(mode=mode, papers=papers):
                with self.assertRaises(session.SessionError):
                    session.init(self.source, self.pack, mode=mode, papers=papers)
        self.assertFalse(self.pack.exists())

    def test_status_is_read_only_even_with_edits(self):
        self.init()
        name = self.write_output()
        self.record()
        (self.pack / name).write_text('User notes')
        def snapshot():
            return {str(p.relative_to(self.pack)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.pack.rglob('*') if p.is_file()}
        before = snapshot()
        self.assertFalse(session.status(self.pack)['ok'])
        self.assertEqual(before, snapshot())

    def test_repeated_record_is_byte_identical(self):
        self.init()
        name = self.write_output()
        first = self.record(name)
        before = self.state_path.read_bytes()
        second = self.record(name)
        self.assertTrue(first['recorded'])
        self.assertFalse(second['recorded'])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_record_does_not_overwrite_outputs(self):
        self.init()
        name = self.write_output()
        before = (self.pack / name).read_bytes()
        self.record(name)
        self.assertEqual((self.pack / name).read_bytes(), before)

    def test_phase_requires_explicit_completion(self):
        self.init()
        name = self.write_output()
        result = self.record(name, phase='extract')
        self.assertEqual(result['next_phase'], 'extract')
        self.assertEqual(result['completed_phases'], [])
        result = self.record(name, phase='extract', complete=True)
        self.assertEqual(result['next_phase'], 'inventory')
        self.assertEqual(result['completed_phases'], ['extract'])
        self.assertFalse(self.record(name, phase='extract', complete=True)['recorded'])

    def test_multiple_chapter_checkpoints_are_retained(self):
        self.init()
        self.write_output()
        self.record()
        second = self.write_output('chapters/ch02.md', '# Chapter 2\n')
        result = self.record(second, key='ch02', complete=True)
        self.assertEqual([c['key'] for c in result['checkpoints']], ['ch01', 'ch02'])
        self.assertIn('notes', result['completed_phases'])

    def test_completed_phase_cannot_silently_reopen(self):
        self.init()
        self.write_output()
        self.record(complete=True)
        other = self.write_output('chapters/ch02.md')
        with self.assertRaisesRegex(session.SessionError, 'already complete'):
            self.record(other, key='ch02')

    def test_changed_input_blocks_record_and_does_not_reset_init(self):
        self.init()
        self.write_output()
        before = self.state_path.read_bytes()
        (self.source / '01.pdf').write_bytes(b'changed')
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertEqual(result['input_changes']['changed'], ['01.pdf'])
        with self.assertRaisesRegex(session.SessionError, 'integrity'):
            self.record()
        self.assertFalse(self.init()['ok'])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_added_and_deleted_inputs_are_detected(self):
        self.init()
        (self.source / '01.pdf').unlink()
        (self.source / '03.pdf').write_bytes(b'new source')
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertEqual(result['input_changes']['missing'], ['01.pdf'])
        self.assertEqual(result['input_changes']['added'], ['03.pdf'])

    def test_missing_input_directory_has_clear_error(self):
        self.init()
        self.source.rename(self.root / 'moved-input')
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertIn('Input:', result['errors'][0])

    def test_user_modified_output_is_never_adopted_or_overwritten(self):
        self.init()
        name = self.write_output()
        self.record()
        before = self.state_path.read_bytes()
        path = self.pack / name
        path.write_text('User edits: keep these.', encoding='utf-8')
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertEqual(result['output_changes']['changed'], [name])
        with self.assertRaisesRegex(session.SessionError, 'integrity'):
            self.record()
        self.assertEqual(path.read_text(), 'User edits: keep these.')
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_preserve_edits_records_new_chapter_without_rebaselining(self):
        self.init()
        name = self.write_output()
        self.record()
        old = json.loads(self.state_path.read_text())['checkpoints'][0]
        (self.pack / name).write_text('Keep my own annotations')
        second = self.write_output('chapters/ch02.md')
        result = session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertTrue(result['recorded'])
        self.assertFalse(result['ok'])
        self.assertEqual(result['preserved_output_edits'], [name])
        self.assertEqual((self.pack / name).read_text(), 'Keep my own annotations')
        self.assertEqual(json.loads(self.state_path.read_text())['checkpoints'][0], old)
        self.assertEqual(len(result['checkpoints']), 2)
        before = self.state_path.read_bytes()
        result = session.record(self.pack, 'notes', 'ch02', [second], preserve_edits=True)
        self.assertFalse(result['recorded'])
        self.assertFalse(result['ok'])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_preserve_edits_cannot_adopt_old_paths_or_finish_a_phase(self):
        self.init()
        name = self.write_output()
        self.record()
        tracked = self.write_output('chapters/unchanged.md')
        self.record(tracked, key='unchanged')
        (self.pack / name).write_text('Keep my own annotations')
        new = self.write_output('chapters/new.md')
        before = self.state_path.read_bytes()
        for files, complete in [([name], False), ([tracked], False), ([new], True)]:
            with self.subTest(files=files, complete=complete):
                with self.assertRaises(session.SessionError):
                    session.record(self.pack, 'notes', 'new', files,
                                   complete_phase=complete, preserve_edits=True)
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_preserve_edits_cannot_bypass_source_changes_or_missing_outputs(self):
        self.init()
        name = self.write_output()
        self.record()
        (self.pack / name).write_text('User notes')
        new = self.write_output('chapters/new.md')
        original_source = (self.source / '01.pdf').read_bytes()
        (self.source / '01.pdf').write_bytes(b'changed')
        with self.assertRaisesRegex(session.SessionError, 'integrity'):
            session.record(self.pack, 'notes', 'new', [new], preserve_edits=True)
        (self.source / '01.pdf').write_bytes(original_source)
        (self.pack / name).unlink()
        with self.assertRaisesRegex(session.SessionError, 'integrity'):
            session.record(self.pack, 'notes', 'new', [new], preserve_edits=True)

    def test_deleted_output_is_detected(self):
        self.init()
        name = self.write_output()
        self.record()
        (self.pack / name).unlink()
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertEqual(result['output_changes']['missing'], [name])

    def test_unrecorded_interrupted_draft_is_flagged_but_preserved(self):
        self.init()
        name = self.write_output(content='unfinished')
        result = session.status(self.pack)
        self.assertTrue(result['ok'])
        self.assertTrue(result['needs_review'])
        self.assertEqual(result['unrecorded_files'], [name])
        self.assertIn('interrupted', result['resume_instructions'][0])
        self.assertEqual((self.pack / name).read_text(), 'unfinished')

    def test_duplicate_key_with_different_files_is_rejected(self):
        self.init()
        self.write_output()
        self.record()
        other = self.write_output('chapters/ch02.md')
        with self.assertRaisesRegex(session.SessionError, 'already records different files'):
            self.record(other)

    def test_multiple_files_duplicate_arguments_and_unicode_names(self):
        self.init()
        one = self.write_output('章节/第一章.md')
        two = self.write_output('章节/第二章.md')
        result = session.record(self.pack, 'notes', 'batch-1', [two, one, one])
        self.assertEqual(result['checkpoints'][0]['files'], sorted([one, two]))

    def test_existing_pack_without_session_is_not_adopted(self):
        self.pack.mkdir()
        path = self.pack / 'user-notes.md'
        path.write_text('Keep me')
        with self.assertRaisesRegex(session.SessionError, 'already contains files'):
            self.init()
        self.assertEqual(path.read_text(), 'Keep me')
        self.assertFalse((self.pack / '_session').exists())

    def test_different_input_cannot_reuse_session(self):
        self.init()
        with self.assertRaisesRegex(session.SessionError, 'different input'):
            session.init(self.source / '01.pdf', self.pack)

    def test_nested_input_and_output_paths_rejected(self):
        for source, output in [(self.source, self.source / 'pack'),
                               (self.source, self.source),
                               (self.source, self.root),
                               (self.source / '01.pdf', self.source)]:
            with self.subTest(source=source, output=output):
                with self.assertRaisesRegex(session.SessionError, 'not nested'):
                    session.init(source, output)

    def test_unsafe_checkpoint_paths_are_rejected(self):
        self.init()
        self.write_output()
        for name in ['../outside.md', '/tmp/outside.md', 'a/../../outside.md',
                     'C:\\outside.md', 'a\\b.md', './chapters/ch01.md',
                     'chapters//ch01.md', 'chapters/../ch01.md',
                     '_session/state.json', '', 'a\x00b']:
            with self.subTest(name=name):
                with self.assertRaises(session.SessionError):
                    self.record(name)

    def test_bad_keys_empty_and_missing_outputs_are_rejected(self):
        self.init()
        for key in ['', '../x', 'space key', '-x', 'x' * 81]:
            with self.subTest(key=key):
                with self.assertRaises(session.SessionError):
                    self.record(key=key)
        with self.assertRaisesRegex(session.SessionError, 'does not exist'):
            self.record()
        self.write_output(content='')
        with self.assertRaisesRegex(session.SessionError, 'empty'):
            self.record()
        with self.assertRaisesRegex(session.SessionError, 'at least one'):
            session.record(self.pack, 'notes', 'ch01', [])

    @unittest.skipUnless(hasattr(os, 'symlink'), 'Symlinks unavailable')
    def test_symlink_input_and_output_are_rejected(self):
        link = self.source / 'linked.pdf'
        self.symlink(link, self.source / '01.pdf')
        with self.assertRaisesRegex(session.SessionError, 'Symlink'):
            self.init()
        link.unlink()
        self.init()
        self.symlink(self.pack / 'linked.md', self.source / '01.pdf')
        result = session.status(self.pack)
        self.assertFalse(result['ok'])
        self.assertIn('Symlink', result['errors'][0])
        with self.assertRaises(session.SessionError):
            self.record('linked.md')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'Symlinks unavailable')
    def test_symlink_directory_and_state_are_rejected(self):
        self.init()
        self.symlink(self.pack / 'outside', self.source, is_directory=True)
        self.assertFalse(session.status(self.pack)['ok'])
        (self.pack / 'outside').unlink()
        original = self.state_path.read_bytes()
        moved = self.root / 'state-copy.json'
        moved.write_bytes(original)
        self.state_path.unlink()
        self.symlink(self.state_path, moved)
        with self.assertRaisesRegex(session.SessionError, 'Symlink'):
            self.init()
        self.assertEqual(moved.read_bytes(), original)

    @unittest.skipUnless(hasattr(os, 'symlink'), 'Symlinks unavailable')
    def test_root_ancestor_alias_is_normalized_but_root_link_is_rejected(self):
        alias = self.root / 'system-alias'
        self.symlink(alias, self.root, is_directory=True)
        result = session.init(alias / 'inputs', alias / 'pack')
        self.assertEqual(result['pack'], str(self.pack))
        self.assertEqual(session.status(alias / 'pack')['pack'], str(self.pack))
        root_link = self.root / 'source-link'
        self.symlink(root_link, self.source, is_directory=True)
        with self.assertRaisesRegex(session.SessionError, 'roots'):
            session.init(root_link, self.root / 'second-pack')

    def test_windows_reparse_point_is_detected(self):
        fake = SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
        with patch.object(Path, 'lstat', return_value=fake):
            self.assertTrue(session._is_link(self.root))

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO unavailable')
    def test_special_file_is_rejected_without_blocking(self):
        os.mkfifo(self.source / 'pipe')
        with self.assertRaisesRegex(session.SessionError, 'regular file'):
            self.init()

    def test_corrupt_state_is_not_overwritten(self):
        self.init()
        self.state_path.write_text('{interrupted manual edit')
        before = self.state_path.read_bytes()
        with self.assertRaisesRegex(session.SessionError, 'unreadable'):
            self.init()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_malformed_state_is_rejected(self):
        self.init()
        data = json.loads(self.state_path.read_text())
        data['checkpoints'] = [{'phase': 'notes', 'key': 'ch01',
                                'files': {'../private': {'sha256': 'a' * 64, 'size': 3}}}]
        self.state_path.write_text(json.dumps(data))
        with self.assertRaises(session.SessionError):
            session.status(self.pack)

    def test_corrupt_source_path_returns_clean_cli_error(self):
        self.init()
        data = json.loads(self.state_path.read_text())
        data['source']['path'] = '\x00'
        self.state_path.write_text(json.dumps(data))
        result = self.cli('status', self.pack)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stderr)['ok'])
        self.assertNotIn('Traceback', result.stderr)

    @unittest.skipUnless(hasattr(os, 'link'), 'Hard links unavailable')
    def test_hard_linked_bookkeeping_lock_cannot_modify_content(self):
        internal = self.pack / '_session'
        internal.mkdir(parents=True)
        original = self.root / 'empty-user-file'
        original.write_bytes(b'')
        os.link(original, internal / '.lock')
        with self.assertRaisesRegex(session.SessionError, 'hard-linked'):
            self.init()
        self.assertEqual(original.read_bytes(), b'')
        self.assertFalse(self.state_path.exists())

    def test_failed_atomic_replace_preserves_previous_state(self):
        self.init()
        self.write_output()
        before = self.state_path.read_bytes()
        with patch.object(session.os, 'replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.record()
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertEqual(list((self.pack / '_session').glob('.state-*.tmp')), [])
        self.assertEqual(session.status(self.pack)['checkpoints'], [])
        self.assertTrue(self.record()['recorded'])

    def test_failed_fsync_preserves_previous_state(self):
        self.init()
        self.write_output()
        before = self.state_path.read_bytes()
        with patch.object(session.os, 'fsync', side_effect=OSError('simulated full disk')):
            with self.assertRaisesRegex(OSError, 'full disk'):
                self.record()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_process_crash_before_replace_resumes_without_lost_checkpoint(self):
        self.init()
        self.write_output()
        before = self.state_path.read_bytes()
        code = (
            'import importlib.util, os; '
            f'spec=importlib.util.spec_from_file_location("session", {str(ROOT / "scripts/session.py")!r}); '
            's=importlib.util.module_from_spec(spec); spec.loader.exec_module(s); '
            's.os.replace=lambda *args: os._exit(91); '
            f's.record({str(self.pack)!r}, "notes", "ch01", ["chapters/ch01.md"])'
        )
        result = subprocess.run([sys.executable, '-c', code], timeout=10)
        self.assertEqual(result.returncode, 91)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertTrue(list((self.pack / '_session').glob('.state-*.tmp')))
        self.assertTrue(session.status(self.pack)['needs_review'])
        # The kernel released the lock even though finally blocks never ran.
        self.assertTrue(self.record()['recorded'])
        self.assertEqual(len(session.status(self.pack)['checkpoints']), 1)

    def test_process_crash_after_replace_has_idempotent_retry(self):
        self.init()
        self.write_output()
        code = (
            'import importlib.util, os\n'
            f'spec=importlib.util.spec_from_file_location("session", {str(ROOT / "scripts/session.py")!r})\n'
            's=importlib.util.module_from_spec(spec); spec.loader.exec_module(s)\n'
            'original_replace=s.os.replace\n'
            'def replace_and_crash(*args):\n'
            '    original_replace(*args)\n'
            '    os._exit(92)\n'
            's.os.replace=replace_and_crash\n'
            f's.record({str(self.pack)!r}, "notes", "ch01", ["chapters/ch01.md"])\n'
        )
        result = subprocess.run([sys.executable, '-c', code], timeout=10)
        self.assertEqual(result.returncode, 92)
        before = self.state_path.read_bytes()
        self.assertEqual(len(session.status(self.pack)['checkpoints']), 1)
        self.assertFalse(self.record()['recorded'])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_interrupted_init_with_only_temporary_bookkeeping_can_retry(self):
        internal = self.pack / '_session'
        internal.mkdir(parents=True)
        (internal / '.state-abcd.tmp').write_text('{partial')
        result = self.init()
        self.assertTrue(result['created'])
        self.assertTrue(session.status(self.pack)['ok'])
        self.assertEqual((internal / '.state-abcd.tmp').read_text(), '{partial')

    def test_interrupted_init_does_not_adopt_content(self):
        (self.pack / '_session').mkdir(parents=True)
        name = self.write_output()
        with self.assertRaisesRegex(session.SessionError, 'contains content'):
            self.init()
        self.assertTrue((self.pack / name).is_file())

    @unittest.skipIf(os.name == 'nt', 'POSIX lock contention check')
    def test_concurrent_writer_is_rejected_without_state_change(self):
        self.init()
        self.write_output()
        before = self.state_path.read_bytes()
        with session._lock(self.pack):
            result = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch01',
                              '--file', 'chapters/ch01.md')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Another session command', result.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertTrue(self.record()['recorded'])

    def test_cli_json_and_change_exit_codes(self):
        result = self.cli('init', self.source, '--out', self.pack)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['created'])
        self.write_output()
        result = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch01',
                          '--file', 'chapters/ch01.md')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['recorded'])
        (self.source / '01.pdf').write_bytes(b'new source')
        result = self.cli('status', self.pack)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(json.loads(result.stdout)['ok'])
        result = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch01',
                          '--file', 'chapters/ch01.md')
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stderr)['content_modified'])

    def test_cli_unicode_paths_work_with_ascii_console_encoding(self):
        pack = self.root / '中文复习包'
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/session.py'), 'init', str(self.source),
             '--out', str(pack), '--mode', 'concise', '--papers', '2'],
            capture_output=True, text=True, encoding='ascii', timeout=10,
            env={**os.environ, 'PYTHONIOENCODING': 'ascii:strict'})
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['pack'], str(pack))
        self.assertEqual(data['settings'], {'mode': 'concise', 'papers': 2})

    def test_preserve_edits_cli_reports_saved_checkpoint_with_conflict_exit(self):
        self.init()
        name = self.write_output()
        self.record()
        (self.pack / name).write_text('User notes')
        new = self.write_output('chapters/ch02.md')
        result = self.cli('record', self.pack, '--phase', 'notes', '--key', 'ch02',
                          '--file', new, '--preserve-edits')
        self.assertEqual(result.returncode, 2, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['recorded'])
        self.assertFalse(data['ok'])
        self.assertEqual(data['preserved_output_edits'], [name])


if __name__ == '__main__':
    unittest.main()
