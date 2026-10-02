import os
import tempfile
import unittest
from pathlib import Path

from harness_fusion import filesystem as fs


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_already_dirty_file_edit_detected_without_git(self):
        p = self.root / "dirty.py"
        p.write_text("previous unsaved work")
        before = fs.snapshot(self.root)
        p.write_text("evaluator changed existing dirty work")
        changed = fs.changes(before, fs.snapshot(self.root))
        self.assertEqual(changed, ["dirty.py"])
        self.assertEqual(fs.violations(changed, "evaluator", []), ["dirty.py"])

    def test_additions_and_deletions_detected(self):
        p = self.root / "old.py"
        p.write_text("old")
        before = fs.snapshot(self.root)
        p.unlink()
        (self.root / "new.py").write_text("new")
        self.assertEqual(fs.changes(before, fs.snapshot(self.root)), ["new.py", "old.py"])

    def test_scope_does_not_cross_path_segments(self):
        self.assertTrue(fs.matches("src/module.py", "src/*.py"))
        self.assertFalse(fs.matches("src/nested/module.py", "src/*.py"))
        self.assertFalse(fs.matches("other/src/module.py", "src/*.py"))
        self.assertFalse(fs.matches("src-evil/module.py", "src/**"))
        self.assertTrue(fs.matches("src/nested/module.py", "src/**"))

    def test_controls_protected_even_in_touch(self):
        changed = ["docs/PRD.md", "harness.toml", ".fusion/state.json", "src/a.py"]
        self.assertEqual(fs.violations(changed, "generator", ["docs/**", "harness.toml", ".fusion/**", "src/**"]), changed[:3])

    def test_atomic_state_roundtrip(self):
        import json
        path = self.root / "state.json"
        fs.atomic_json(path, {"한글": [1, 2]})
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"한글": [1, 2]})
        self.assertFalse(path.with_name("state.json.tmp").exists())

    def test_project_lock_releases_after_error(self):
        with self.assertRaises(ValueError):
            with fs.project_lock(self.root):
                raise ValueError("interrupted")
        with fs.project_lock(self.root):
            pass

    def test_snapshot_during_lock_and_competing_lock(self):
        with fs.project_lock(self.root):
            before = fs.snapshot(self.root)
            self.assertIn(".fusion/lock", before)
            with self.assertRaises(RuntimeError):
                with fs.project_lock(self.root):
                    self.fail("Second lock must not succeed")
            self.assertEqual(before, fs.snapshot(self.root))

    def test_lock_metadata_changes_are_protected(self):
        with fs.project_lock(self.root):
            before = fs.snapshot(self.root)
        (self.root / ".fusion/lock").write_bytes(b"changed")
        changed = fs.changes(before, fs.snapshot(self.root))
        self.assertEqual(changed, [".fusion/lock"])
        self.assertEqual(fs.violations(changed, "generator", [".fusion/**"]), changed)

    def test_symlink_rejected(self):
        (self.root / "original").write_text("text")
        try:
            (self.root / "link").symlink_to(self.root / "original")
        except OSError:
            self.skipTest("OS does not permit symlinks")
        with self.assertRaises(ValueError):
            fs.snapshot(self.root)

    @unittest.skipIf(os.name == "nt", "POSIX file mode semantics")
    def test_mode_change_detected(self):
        p = self.root / "file"
        p.write_text("text")
        before = fs.snapshot(self.root)
        p.chmod(0o700)
        self.assertEqual(fs.changes(before, fs.snapshot(self.root)), ["file"])
