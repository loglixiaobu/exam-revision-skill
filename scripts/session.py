#!/usr/bin/env python3
"""Track local revision work; never generate, edit, delete, or overwrite course content.

Only _session/state.json and its lock/temporary bookkeeping files are written.
The host model writes and reviews each new content file before recording it.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile

PHASES = ('extract', 'inventory', 'notes', 'practice', 'answers', 'audit')
SESSION_DIR = '_session'
STATE_NAME = 'state.json'
KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')


def _ignored_input(name):
    # Ignore only known input-side application/OS housekeeping, never outputs.
    return name.startswith('~$') or name.casefold() in {'.ds_store', 'thumbs.db', 'desktop.ini'}


class SessionError(ValueError):
    """A safe, actionable refusal; content files have not been modified."""


def _absolute(path):
    requested = Path(os.path.abspath(os.path.expanduser(os.fspath(path))))
    if _is_link(requested):
        raise SessionError(f'Symlink/junction roots are not accepted: {requested}')
    # Normal OS aliases such as macOS /tmp and /var may be ancestors. Resolve
    # those once at the user-selected root; descendants remain strictly checked.
    return requested.parent.resolve() / requested.name


def _is_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0)
                    & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def _no_symlinks(path):
    for part in (*reversed(path.parents), path):
        if _is_link(part):
            raise SessionError(f'Symlink/junction paths are not accepted: {part}')


def _relative(value):
    # Backslashes and drive prefixes are rejected even on POSIX so a saved
    # checkpoint cannot acquire a different meaning on Windows.
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\x00' in value:
        raise SessionError(f'Expected a plain relative file path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise SessionError(f'Path must stay inside the pack: {value!r}')
    if path.parts[0] == SESSION_DIR:
        raise SessionError('Session bookkeeping cannot be recorded as study content')
    return value


def _separate(source, pack, kind):
    if source == pack or pack in source.parents or (kind == 'directory' and source in pack.parents):
        raise SessionError('Input and output paths must be separate, not nested')


def _hash_file(path):
    _no_symlinks(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise SessionError(f'Not a regular file: {path}')
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
             | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0))
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise SessionError(f'Not a regular file: {path}')
        digest = hashlib.sha256()
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise SessionError(f'File changed while being read; retry when writing stops: {path}')
        return {'sha256': digest.hexdigest(), 'size': after.st_size}


def _snapshot(root, kind, exclude_session=False):
    _no_symlinks(root)
    if kind == 'file':
        if not root.is_file():
            raise SessionError(f'Input file is missing or no longer a regular file: {root}')
        if _ignored_input(root.name):
            return {}
        return {root.name: _hash_file(root)}
    if not root.is_dir():
        raise SessionError(f'Directory is missing or no longer a directory: {root}')
    found = {}

    def onerror(error):
        raise error

    for base, directories, files in os.walk(root, followlinks=False, onerror=onerror):
        base = Path(base)
        if exclude_session and base == root:
            directories[:] = [d for d in directories if d != SESSION_DIR]
        for name in sorted(directories):
            _no_symlinks(base / name)
        for name in sorted(files):
            if not exclude_session and _ignored_input(name):
                continue
            path = base / name
            if exclude_session and base == root and name == SESSION_DIR:
                raise SessionError(f'Expected a session directory: {path}')
            relative = path.relative_to(root).as_posix()
            # The same path rules apply to saved source and output manifests.
            if exclude_session:
                _relative(relative)
            found[relative] = _hash_file(path)
    return dict(sorted(found.items()))


@contextmanager
def _lock(pack):
    internal = pack / SESSION_DIR
    _no_symlinks(internal)
    lock_path = internal / '.lock'
    _no_symlinks(lock_path)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'r+b') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise SessionError(f'Not a regular lock file: {lock_path}')
        if info.st_nlink != 1:
            raise SessionError('Session lock must not be hard-linked to another file')
        if os.name == 'nt':
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SessionError('Another session command is running; wait and retry') from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SessionError('Another session command is running; wait and retry') from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _save(pack, data):
    """Replace bookkeeping atomically on the same filesystem, after fsync."""
    internal = pack / SESSION_DIR
    target = internal / STATE_NAME
    _no_symlinks(target)
    fd, temporary = tempfile.mkstemp(prefix='.state-', suffix='.tmp', dir=internal)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if os.name != 'nt':
            directory_fd = os.open(internal, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                try:
                    os.fsync(directory_fd)
                except OSError as exc:
                    if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                        raise
            finally:
                os.close(directory_fd)
    finally:
        # An abrupt process kill may leave a temporary file. Future commands
        # ignore it and trust only the fully replaced state.json, never it.
        if os.path.exists(temporary):
            os.unlink(temporary)


def _metadata(value):
    return (isinstance(value, dict)
            and isinstance(value.get('sha256'), str)
            and DIGEST.fullmatch(value['sha256'])
            and type(value.get('size')) is int and value['size'] >= 0)


def _validate(data, pack):
    try:
        if (type(data['schema_version']) is not int or data['schema_version'] != 1 or data['pack'] != str(pack)
                or data['phases'] != list(PHASES)
                or type(data['revision']) is not int or data['revision'] < 0):
            raise SessionError('Unsupported state schema, revision, or moved output directory')
        settings = data['settings']
        if (settings['mode'] not in ('detailed', 'concise', 'both')
                or type(settings['papers']) is not int or settings['papers'] < 1):
            raise SessionError('Invalid saved revision mode or paper count')
        source = data['source']
        if (source['kind'] not in ('file', 'directory') or not isinstance(source['path'], str)
                or not source['path'] or '\x00' in source['path']):
            raise SessionError('Invalid source description')
        source_path = _absolute(source['path'])
        if str(source_path) != source['path']:
            raise SessionError('Source path must be an absolute normalized path')
        _separate(source_path, pack, source['kind'])
        if not isinstance(source['files'], dict) or not source['files']:
            raise SessionError('Source manifest is empty or invalid')
        for name, value in source['files'].items():
            # Input filenames may contain a colon on POSIX, but no traversals.
            if (not isinstance(name, str) or not name or '\\' in name
                    or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))
                    or not _metadata(value)):
                raise SessionError('Invalid source manifest entry')
        if source['kind'] == 'file' and list(source['files']) != [source_path.name]:
            raise SessionError('Source file manifest does not match its path')
        completed = data['completed_phases']
        if (not isinstance(completed, list) or any(p not in PHASES for p in completed)
                or len(set(completed)) != len(completed)):
            raise SessionError('Invalid completed phase list')
        seen, outputs, recorded_phases = set(), {}, set()
        if not isinstance(data['checkpoints'], list):
            raise SessionError('Invalid checkpoint list')
        for item in data['checkpoints']:
            if item['phase'] not in PHASES or not isinstance(item['key'], str) or not KEY.fullmatch(item['key']):
                raise SessionError('Invalid checkpoint phase or key')
            identity = (item['phase'], item['key'])
            if identity in seen:
                raise SessionError('Duplicate checkpoint key')
            seen.add(identity)
            recorded_phases.add(item['phase'])
            if not isinstance(item['files'], dict) or not item['files']:
                raise SessionError('Checkpoint has no file evidence')
            for name, value in item['files'].items():
                _relative(name)
                if not _metadata(value) or value['size'] == 0:
                    raise SessionError('Invalid checkpoint file hash or size')
                if name in outputs and outputs[name] != value:
                    raise SessionError('Conflicting hashes for one output file')
                outputs[name] = value
        if any(p not in recorded_phases for p in completed):
            raise SessionError('Completed phase has no checkpoint evidence')
    except (KeyError, TypeError, AttributeError) as exc:
        raise SessionError('Session state is malformed; preserve it and start a new output directory') from exc


def _load(pack):
    _no_symlinks(pack)
    path = pack / SESSION_DIR / STATE_NAME
    _no_symlinks(path)
    if not path.is_file():
        raise SessionError('No saved session. Run init with the original input and a new/empty output directory')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise SessionError('Session state is unreadable; do not replace it or trust temporary files. Preserve the pack and start a new output directory') from exc
    _validate(data, pack)
    return data


def _diff(expected, actual):
    return {
        'added': sorted(actual.keys() - expected.keys()),
        'missing': sorted(expected.keys() - actual.keys()),
        'changed': sorted(name for name in expected.keys() & actual.keys() if expected[name] != actual[name]),
    }


def _inspect(pack, data):
    errors = []
    source = data['source']
    try:
        inputs = _snapshot(Path(source['path']), source['kind'])
        input_changes = _diff(source['files'], inputs)
    except (OSError, SessionError) as exc:
        errors.append('Input: ' + str(exc))
        input_changes = {'added': [], 'missing': [], 'changed': []}
    expected = {name: metadata for item in data['checkpoints'] for name, metadata in item['files'].items()}
    try:
        outputs = _snapshot(pack, 'directory', exclude_session=True)
        output_changes = _diff(expected, outputs)
    except (OSError, SessionError) as exc:
        errors.append('Output: ' + str(exc))
        output_changes = {'added': [], 'missing': [], 'changed': []}
    unrecorded = output_changes.pop('added')
    safe = not errors and not any(input_changes.values()) and not any(output_changes.values())
    can_preserve = (not errors and not any(input_changes.values())
                    and not output_changes['missing'] and bool(output_changes['changed']))
    pending = [p for p in PHASES if p not in data['completed_phases']]
    instructions = [
        'Read the saved checkpoints and existing files before continuing. Never regenerate or overwrite an existing content path.',
        'Use the saved mode/paper settings and read _work/session-context.md (or 00-开始阅读.md) for the user\'s language, exam scope, question types, and other decisions.',
        'For unfinished work, write a new file, review it, then record its phase/key and relative path. Only mark a phase complete after all its work is checked.',
    ]
    if unrecorded:
        instructions.insert(0, 'Review every unrecorded file: it may be an interrupted draft or user-authored content. Record it only after review, or leave it untouched and use a new filename.')
    if not safe:
        instructions.insert(0, 'STOP: sources or recorded outputs changed or cannot be verified. Preserve all files. Restore the exact original bytes only with user approval, or start a new output directory using the current inputs; do not rebaseline this session.')
        if can_preserve:
            instructions.insert(1, 'To keep user-edited files untouched and continue new work, record only NEW paths/keys with --preserve-edits. Original hashes stay unchanged; conflicts remain visible, and no phase may be marked complete while conflicts remain.')
    if safe and not pending:
        instructions.append('All phases were explicitly marked complete. This tracker verifies file identity, not factual accuracy, coverage, or answer correctness.')
    return {
        'ok': safe,
        'pack': str(pack),
        'revision': data['revision'],
        'settings': data['settings'],
        'completed_phases': data['completed_phases'],
        'pending_phases': pending,
        'next_phase': pending[0] if pending else None,
        'checkpoints': [{'phase': c['phase'], 'key': c['key'], 'files': sorted(c['files'])} for c in data['checkpoints']],
        'input_changes': input_changes,
        'output_changes': output_changes,
        'unrecorded_files': unrecorded,
        'needs_review': bool(unrecorded) or not safe,
        'can_continue_with_preserved_edits': can_preserve,
        'errors': errors,
        'resume_instructions': instructions,
    }


def status(pack):
    pack = _absolute(pack)
    return _inspect(pack, _load(pack))


def init(source, pack, mode=None, papers=None):
    if mode is not None and mode not in ('detailed', 'concise', 'both'):
        raise SessionError('Mode must be detailed, concise, or both')
    if papers is not None and (type(papers) is not int or papers < 1):
        raise SessionError('Paper count must be a positive integer')
    source, pack = _absolute(source), _absolute(pack)
    _no_symlinks(source)
    _no_symlinks(pack)
    if not source.exists():
        raise SessionError(f'Input does not exist: {source}')
    kind = 'file' if source.is_file() else 'directory'
    _separate(source, pack, kind)
    if pack.exists() and not pack.is_dir():
        raise SessionError('Output path is not a directory')
    if pack.exists() and not (pack / SESSION_DIR).exists() and any(pack.iterdir()):
        raise SessionError('Output directory already contains files; choose a new directory')
    pack.mkdir(parents=True, exist_ok=True)
    (pack / SESSION_DIR).mkdir(exist_ok=True)
    with _lock(pack):
        target = pack / SESSION_DIR / STATE_NAME
        _no_symlinks(target)
        if target.exists():
            data = _load(pack)
            if data['source']['path'] != str(source) or data['source']['kind'] != kind:
                raise SessionError('This session belongs to a different input; choose a new output directory')
            if ((mode is not None and data['settings']['mode'] != mode)
                    or (papers is not None and data['settings']['papers'] != papers)):
                raise SessionError('Saved mode/paper settings differ; preserve this pack and choose a new output directory')
            result = _inspect(pack, data)
            result['created'] = False
            return result
        # Interrupted init may have created only bookkeeping. Do not adopt a
        # pre-existing pack or silently turn pre-existing notes into outputs.
        if any(p.name != SESSION_DIR for p in pack.iterdir()):
            raise SessionError('Uninitialized output directory contains content; choose a new directory')
        internal = pack / SESSION_DIR
        allowed = lambda p: p.name == '.lock' or (p.name.startswith('.state-') and p.name.endswith('.tmp'))
        if any(not allowed(p) or not p.is_file() or p.is_symlink() for p in internal.iterdir()):
            raise SessionError('Unrecognized session bookkeeping; preserve it and choose a new directory')
        files = _snapshot(source, kind)
        if not files:
            raise SessionError('Input contains no regular course files after ignoring temporary housekeeping files')
        data = {
            'schema_version': 1,
            'pack': str(pack),
            'source': {'path': str(source), 'kind': kind, 'files': files},
            'settings': {'mode': mode or 'detailed', 'papers': papers if papers is not None else 3},
            'phases': list(PHASES),
            'completed_phases': [],
            'checkpoints': [],
            'revision': 0,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }
        _validate(data, pack)
        _save(pack, data)
        result = _inspect(pack, data)
        result['created'] = True
        return result


def record(pack, phase, key, files, complete_phase=False, preserve_edits=False):
    pack = _absolute(pack)
    if phase not in PHASES or not isinstance(key, str) or not KEY.fullmatch(key):
        raise SessionError('Use a known phase and a key of 1-80 ASCII letters, digits, dots, underscores or hyphens, starting with a letter or digit')
    if not files:
        raise SessionError('A checkpoint must reference at least one reviewed file')
    relative_files = sorted({_relative(os.fspath(p)) for p in files})
    _load(pack)  # Validate before opening any bookkeeping path for writing.
    with _lock(pack):
        data = _load(pack)
        inspection = _inspect(pack, data)
        previous = next((c for c in data['checkpoints'] if c['phase'] == phase and c['key'] == key), None)
        if not inspection['ok']:
            if not (preserve_edits and inspection['can_continue_with_preserved_edits']):
                raise SessionError('Cannot record: source/output integrity check failed. Run status and preserve the existing pack')
            if complete_phase:
                raise SessionError('Cannot complete any phase while preserved output edits remain unresolved')
            tracked = {name for c in data['checkpoints'] for name in c['files']}
            if ((previous is None and tracked.intersection(relative_files))
                    or set(inspection['output_changes']['changed']).intersection(relative_files)):
                raise SessionError('With --preserve-edits, a new checkpoint must use new paths; edited/tracked files cannot be adopted or rebaselined')
        evidence = {}
        for name in relative_files:
            path = pack / name
            if not path.is_file():
                raise SessionError(f'Checkpoint output does not exist or is not a regular file: {name}')
            metadata = _hash_file(path)
            if metadata['size'] == 0:
                raise SessionError(f'Checkpoint output is empty: {name}')
            evidence[name] = metadata
        if previous and previous['files'] != evidence:
            raise SessionError('Checkpoint key already records different files; do not replace it. Use a new key and new content paths for additional work')
        if previous is None and phase in data['completed_phases']:
            raise SessionError('Phase is already complete; do not silently reopen it. Preserve this pack and use a new session for revisions')
        changed = previous is None or (complete_phase and phase not in data['completed_phases'])
        if changed:
            if previous is None:
                data['checkpoints'].append({'phase': phase, 'key': key, 'files': evidence})
            if complete_phase and phase not in data['completed_phases']:
                data['completed_phases'].append(phase)
                data['completed_phases'].sort(key=PHASES.index)
            data['revision'] += 1
            _validate(data, pack)
            _save(pack, data)
        result = _inspect(pack, data)
        result['recorded'] = changed
        if preserve_edits and inspection['can_continue_with_preserved_edits']:
            result['preserved_output_edits'] = inspection['output_changes']['changed']
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('init', help='Hash inputs and initialize a new or empty pack directory')
    start.add_argument('input')
    start.add_argument('--out', required=True)
    start.add_argument('--mode', choices=('detailed', 'concise', 'both'), help='Saved for resume; new-session default: detailed')
    start.add_argument('--papers', type=int, help='Saved positive paper count; new-session default: 3')
    view = commands.add_parser('status', help='Verify saved hashes and show where to resume')
    view.add_argument('pack')
    checkpoint = commands.add_parser('record', help='Record existing reviewed files; never write their contents')
    checkpoint.add_argument('pack')
    checkpoint.add_argument('--phase', choices=PHASES, required=True)
    checkpoint.add_argument('--key', required=True, help='Stable per-chapter/batch key, e.g. ch01 or paper-A')
    checkpoint.add_argument('--file', action='append', required=True, dest='files', help='Pack-relative existing file; repeat for a group')
    checkpoint.add_argument('--complete-phase', action='store_true', help='Explicitly assert all work in this phase is reviewed')
    checkpoint.add_argument('--preserve-edits', action='store_true', help='Keep edited tracked files and original hashes; record new paths only, without completing a phase')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            result = init(args.input, args.out, args.mode, args.papers)
        elif args.command == 'status':
            result = status(args.pack)
        else:
            result = record(args.pack, args.phase, args.key, args.files, args.complete_phase, args.preserve_edits)
        # ASCII JSON escapes remain valid and round-trip Unicode paths even on
        # older Windows consoles that cannot encode the source language.
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result['ok'] else 2
    except (ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'content_modified': False}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
