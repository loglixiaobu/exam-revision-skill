"""Local installer safety and repeatability; no third-party dependencies."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("install_skill_test_module", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="exam install test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source repository"
        self.project = self.root / "study project 中文"
        self.source.mkdir()
        self.project.mkdir()
        for name in installer.RUNTIME_FILES:
            file = self.source / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(f"runtime fixture: {name}\n".encode())
        self.target = self.project / installer.SKILL_LOCATION

    def run_install(self, **kwargs):
        return installer.install_skill(self.source, self.project, **kwargs)

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlink creation is unavailable: {error}")

    def test_default_preview_does_not_create_anything(self):
        status, target, count = self.run_install()
        self.assertEqual((status, target, count), ("preview", self.target, len(installer.RUNTIME_FILES)))
        self.assertEqual(list(self.project.iterdir()), [])

    def test_fresh_install_only_copies_runtime_allowlist(self):
        for name in ("private/course.pdf", "examples/lesson.docx", "tests/test_secret.py", ".git/config", "scripts/not-approved.py", "references/private.md"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("must stay private", encoding="utf-8")
        status, _, count = self.run_install(install=True)
        self.assertEqual(status, "installed")
        self.assertEqual(count, len(installer.RUNTIME_FILES))
        files = {p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(files, set(installer.RUNTIME_FILES))
        for name in files:
            self.assertEqual((self.target / name).read_bytes(), (self.source / name).read_bytes())

    def test_repeated_install_and_verify_are_idempotent(self):
        self.run_install(install=True)
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(self.run_install(install=True)[0], "identical")
        self.assertEqual(self.run_install(verify=True)[0], "identical")
        after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_modified_install_is_not_overwritten(self):
        self.run_install(install=True)
        (self.target / "SKILL.md").write_text("my edits", encoding="utf-8")
        for action in ({}, {"install": True}, {"verify": True}):
            with self.assertRaisesRegex(installer.InstallError, "modified: SKILL.md"):
                self.run_install(**action)
        self.assertEqual((self.target / "SKILL.md").read_text(), "my edits")

    def test_extra_file_is_preserved_and_rejected(self):
        self.run_install(install=True)
        extra = self.target / "private.pdf"
        extra.write_bytes(b"private")
        with self.assertRaisesRegex(installer.InstallError, "extra: private.pdf"):
            self.run_install(install=True)
        self.assertEqual(extra.read_bytes(), b"private")

    def test_extra_empty_directory_is_rejected(self):
        self.run_install(install=True)
        (self.target / "extra").mkdir()
        with self.assertRaisesRegex(installer.InstallError, "extra directory: extra"):
            self.run_install(install=True)

    def test_missing_installed_file_is_not_silently_repaired(self):
        self.run_install(install=True)
        (self.target / "SKILL.md").unlink()
        with self.assertRaisesRegex(installer.InstallError, "missing: SKILL.md"):
            self.run_install(install=True)
        self.assertFalse((self.target / "SKILL.md").exists())

    def test_verify_missing_install_does_not_write(self):
        with self.assertRaisesRegex(installer.InstallError, "not installed"):
            self.run_install(verify=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_missing_source_runtime_file_stops_before_writing(self):
        (self.source / "SKILL.md").unlink()
        with self.assertRaisesRegex(installer.InstallError, "Required runtime file is missing"):
            self.run_install(install=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_missing_project_is_not_created(self):
        missing = self.root / "missing"
        with self.assertRaisesRegex(installer.InstallError, "Project must be an existing directory"):
            installer.install_skill(self.source, missing, install=True)
        self.assertFalse(missing.exists())

    def test_destination_parent_file_is_not_changed(self):
        (self.project / ".agents").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "Expected a directory"):
            self.run_install(install=True)
        self.assertEqual((self.project / ".agents").read_text(), "keep")

    def test_destination_file_is_not_changed(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(installer.InstallError, "not a directory"):
            self.run_install(install=True)
        self.assertEqual(self.target.read_text(), "keep")

    def test_linked_destination_parent_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.symlink(self.project / ".agents", outside, directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            self.run_install(install=True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_dangling_destination_link_is_rejected(self):
        self.target.parent.mkdir(parents=True)
        outside = self.root / "nonexistent"
        self.symlink(self.target, outside, directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            self.run_install(install=True)
        self.assertFalse(outside.exists())

    def test_linked_project_is_rejected(self):
        alias = self.root / "alias"
        self.symlink(alias, self.project, directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            installer.install_skill(self.source, alias, install=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_linked_source_file_is_rejected(self):
        (self.source / "SKILL.md").unlink()
        private = self.root / "private.md"
        private.write_text("private", encoding="utf-8")
        self.symlink(self.source / "SKILL.md", private)
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            self.run_install(install=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_linked_source_directory_is_rejected(self):
        references = self.source / "references"
        outside = self.root / "outside references"
        references.rename(outside)
        self.symlink(references, outside, directory=True)
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            self.run_install(install=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_windows_reparse_point_is_rejected(self):
        info = mock.Mock(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
                installer._kind(Path("junction"))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named pipes are not available")
    def test_special_source_file_is_rejected_without_opening(self):
        source = self.source / "SKILL.md"
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(installer.InstallError, "special filesystem entry"):
            self.run_install(install=True)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_write_failure_preserves_incomplete_directory(self):
        original_open = Path.open

        def fail_for_skill_file(path, mode="r", *args, **kwargs):
            if path == self.target / "SKILL.md" and mode == "xb":
                raise OSError("simulated disk full")
            return original_open(path, mode, *args, **kwargs)

        with mock.patch.object(Path, "open", fail_for_skill_file):
            with self.assertRaisesRegex(installer.InstallError, "incomplete installation may remain"):
                self.run_install(install=True)
        self.assertTrue(self.target.is_dir())
        with self.assertRaisesRegex(installer.InstallError, "Existing installation differs"):
            self.run_install(install=True)

    def test_destination_created_during_install_is_not_overwritten(self):
        original_mkdir = Path.mkdir
        sentinel = self.target / "other-users-note.txt"

        def race_at_target(path, *args, **kwargs):
            if path == self.target:
                original_mkdir(path)
                sentinel.write_text("keep this", encoding="utf-8")
            return original_mkdir(path, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", race_at_target):
            with self.assertRaisesRegex(installer.InstallError, "No existing files were overwritten"):
                self.run_install(install=True)
        self.assertEqual(sentinel.read_text(), "keep this")
        self.assertEqual(list(self.target.iterdir()), [sentinel])

    def test_cli_dependencies_missing_returns_two_without_writes(self):
        with mock.patch.object(installer, "install_skill", return_value=("preview", self.target, len(installer.RUNTIME_FILES))), mock.patch.object(installer.importlib.util, "find_spec", return_value=None), contextlib.redirect_stdout(io.StringIO()) as output:
            result = installer.main(["--project", str(self.project), "--check-deps"])
        self.assertEqual(result, 2)
        self.assertIn("No files were changed", output.getvalue())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_dependency_check_rejects_out_of_range_version(self):
        with mock.patch.object(installer.importlib.util, "find_spec", return_value=object()), mock.patch.object(installer.importlib.metadata, "version", return_value="7.0.0"), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(installer.check_dependencies())
        self.assertIn("needs pypdf>=5,<7", output.getvalue())

    def test_dependency_check_accepts_supported_version(self):
        with mock.patch.object(installer.importlib.util, "find_spec", return_value=object()), mock.patch.object(installer.importlib.metadata, "version", return_value="6.0.0"), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertTrue(installer.check_dependencies())
        self.assertIn("pypdf: 6.0.0 (OK)", output.getvalue())

    def test_linked_file_in_existing_install_is_rejected(self):
        self.run_install(install=True)
        file = self.target / "SKILL.md"
        file.unlink()
        self.symlink(file, self.source / "SKILL.md")
        with self.assertRaisesRegex(installer.InstallError, "symbolic link or junction"):
            self.run_install(verify=True)

    def test_cli_default_and_install_with_space_and_unicode_paths(self):
        command = [sys.executable, str(ROOT / "scripts/install.py"), "--project", str(self.project)]
        preview = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Preview only", preview.stdout)
        self.assertFalse(self.target.exists())
        installed = subprocess.run(command + ["--install"], text=True, capture_output=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        verified = subprocess.run(command + ["--verify"], text=True, capture_output=True)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("identical", verified.stdout)

    def test_cli_unicode_path_does_not_fail_with_ascii_output(self):
        # Use a self-contained source fixture, including the real installer.
        (self.source / "scripts/install.py").write_bytes((ROOT / "scripts/install.py").read_bytes())
        result = subprocess.run(
            [sys.executable, str(self.source / "scripts/install.py"), "--project", str(self.project), "--install"],
            env={**os.environ, "PYTHONIOENCODING": "ascii"},
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Installed and verified", result.stdout)
        self.assertTrue((self.target / "SKILL.md").is_file())

    def test_installed_runtime_can_extract_and_resume_with_preserved_edits(self):
        installer.install_skill(ROOT, self.project, install=True)

        def cli(script, *arguments, expected=0):
            result = subprocess.run(
                [sys.executable, str(self.target / "scripts" / script), *map(str, arguments)],
                text=True, encoding="utf-8", capture_output=True, timeout=15,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result.stdout

        # All commands run from the installed copy, not the original checkout.
        for script in ("extract_sources.py", "check_pack.py", "session.py", "install.py"):
            self.assertIn("usage:", cli(script, "--help"))
        cli("install.py", "--project", self.project, "--verify")
        inputs = self.root / "course inputs"
        inputs.mkdir()
        xml = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Binary search requires sorted input.</w:t>'
            '</w:r></w:p></w:body></w:document>'
        )
        with zipfile.ZipFile(inputs / "lesson.docx", "w") as archive:
            archive.writestr("word/document.xml", xml)
        pack = self.project / "revision output"
        started = json.loads(cli("session.py", "init", inputs, "--out", pack, "--mode", "both", "--papers", 2))
        self.assertEqual(started["settings"], {"mode": "both", "papers": 2})
        cli("extract_sources.py", inputs, "--out", pack / "_sources")
        recorded = json.loads(cli(
            "session.py", "record", pack, "--phase", "extract", "--key", "sources-v1",
            "--file", "_sources/manifest.json", "--file", "_sources/sources.md", "--complete-phase",
        ))
        self.assertEqual(recorded["next_phase"], "inventory")
        first = pack / "chapter-1.md"
        first.write_text("# Chapter 1\nOriginal reviewed notes.\n", encoding="utf-8")
        cli("session.py", "record", pack, "--phase", "notes", "--key", "ch01", "--file", first.name)
        first.write_text("My own annotations must stay.\n", encoding="utf-8")
        (pack / "chapter-2.md").write_text("# Chapter 2\nNew reviewed notes.\n", encoding="utf-8")
        continued = json.loads(cli(
            "session.py", "record", pack, "--phase", "notes", "--key", "ch02",
            "--file", "chapter-2.md", "--preserve-edits", expected=2,
        ))
        self.assertTrue(continued["recorded"])
        self.assertEqual(continued["preserved_output_edits"], ["chapter-1.md"])
        resumed = json.loads(cli("session.py", "status", pack, expected=2))
        self.assertEqual(resumed["settings"], started["settings"])
        self.assertEqual([item["key"] for item in resumed["checkpoints"]], ["sources-v1", "ch01", "ch02"])
        self.assertEqual(first.read_text(encoding="utf-8"), "My own annotations must stay.\n")
        # Runtime calls must not create state, private inputs, or caches inside
        # the installed skill directory itself.
        cli("install.py", "--project", self.project, "--verify")

    def test_dependency_check_reports_missing_without_installing(self):
        with mock.patch.object(installer.importlib.util, "find_spec", return_value=None), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(installer.check_dependencies())
        self.assertIn("not installed", output.getvalue())
        self.assertIn("No packages were installed", output.getvalue())
        self.assertEqual(list(self.project.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
