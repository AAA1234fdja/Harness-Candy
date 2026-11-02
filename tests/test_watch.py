"""Tests del watcher de archivos (watch.py)."""
import tempfile
import time
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.watch import WatchEvent, WatchRunner, changed_since, diff_snapshots, snapshot


class TestWatch(unittest.TestCase):
    def test_snapshot_detecta_archivos(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_text("x = 1\n", encoding="utf-8")
            snap = snapshot(td, ["*.py"])
            self.assertIn("a.py", snap)
            self.assertIn("sha256", snap["a.py"])

    def test_diff_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.txt"
            p.write_text("v1", encoding="utf-8")
            s1 = snapshot(td, ["*.txt"])
            p.write_text("v2", encoding="utf-8")
            (Path(td) / "b.txt").write_text("nuevo", encoding="utf-8")
            s2 = snapshot(td, ["*.txt"])
            d = diff_snapshots(s1, s2)
            self.assertTrue(any("a.txt" in x for x in d["modified"]))
            self.assertTrue(any("b.txt" in x for x in d["added"]))
            (Path(td) / "b.txt").unlink()
            d2 = diff_snapshots(s2, snapshot(td, ["*.txt"]))
            self.assertTrue(any("b.txt" in x for x in d2["deleted"]))

    def test_sin_cambios(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.txt").write_text("v1", encoding="utf-8")
            s = snapshot(td, ["*.txt"])
            d = diff_snapshots(s, snapshot(td, ["*.txt"]))
            self.assertFalse(any(d.values()))

    def test_exclusion_git(self):
        with tempfile.TemporaryDirectory() as td:
            git = Path(td) / ".git"
            git.mkdir()
            (git / "config").write_text("x", encoding="utf-8")
            (Path(td) / "ok.txt").write_text("y", encoding="utf-8")
            snap = snapshot(td, ["**/*"])
            self.assertIn("ok.txt", snap)
            self.assertNotIn(".git/config", snap)

    def test_watchrunner_poll_once(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.txt"
            p.write_text("v1", encoding="utf-8")
            eventos: list[WatchEvent] = []
            w = WatchRunner(td, eventos.append, globs=["*.txt"])
            self.assertIsNone(w.poll_once())  # baseline tomado en __init__
            p.write_text("v2", encoding="utf-8")
            ev = w.poll_once()
            self.assertIsNotNone(ev)
            self.assertTrue(ev.hay_cambios)
            self.assertEqual(eventos, [ev])
            self.assertIsNone(w.poll_once())  # ya no hay cambios

    def test_watchrunner_start_stop_hilo(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.txt"
            p.write_text("v1", encoding="utf-8")
            eventos: list[WatchEvent] = []
            w = WatchRunner(td, eventos.append, globs=["*.txt"], interval_s=0.05)
            w.start()
            self.assertTrue(w.is_running())
            time.sleep(0.1)
            p.write_text("v2-cambio", encoding="utf-8")
            time.sleep(0.3)
            w.stop()
            self.assertFalse(w.is_running())
            self.assertTrue(eventos)

    def test_changed_since(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.txt").write_text("v1", encoding="utf-8")
            s = snapshot(td, ["*.txt"])
            (Path(td) / "a.txt").write_text("v2", encoding="utf-8")
            d = changed_since(s, td, ["*.txt"])
            self.assertTrue(any("a.txt" in x for x in d["modified"]))

    def test_watch_event_to_dict(self):
        ev = WatchEvent(ts=1.0, changes={"added": ["x"], "modified": [], "deleted": []})
        self.assertTrue(ev.hay_cambios)
        d = ev.to_dict()
        self.assertEqual(d["changes"]["added"], ["x"])


if __name__ == "__main__":
    unittest.main()
