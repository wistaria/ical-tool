"""Run the launchers with real Python and hostile user Python settings."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

from icalendar import Calendar


REPO_ROOT = Path(__file__).resolve().parents[1]


def snapshot(directory):
    """Record directories as well as file contents to catch empty cache artifacts."""
    return {
        path.relative_to(directory): (
            ("directory", None) if path.is_dir() else ("file", path.read_bytes())
        )
        for path in directory.rglob("*")
    }


class RuntimeIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ical-tool-isolation-test-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.project = root / "project space 日本語"
        self.home = root / "home"
        self.work = root / "work"
        self.cache = root / "cache"
        for directory in (self.project, self.home, self.work, self.cache):
            directory.mkdir()
        for filename in ("ical-tool", "ical-tool.py", "_ical_tool_env.sh", "run-tests"):
            shutil.copy2(REPO_ROOT / filename, self.project / filename)

        # Reuse this test process's dependencies without creating or installing a venv.
        (self.project / "_ical_tool_env.py").write_text(
            "import os\nprint(os.environ['TEST_CACHED_VENV'])\n", encoding="utf-8"
        )
        self.venv = self.cache / "test-venv"
        (self.venv / "bin").mkdir(parents=True)
        python_bridge = self.venv / "bin" / "python"
        python_bridge.write_text(
            f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8"
        )
        python_bridge.chmod(0o755)

        fixture_tests = self.project / "tests"
        fixture_tests.mkdir()
        (fixture_tests / "__init__.py").write_text("", encoding="utf-8")
        (fixture_tests / "support.py").write_text("MARKER = 'fixture'\n", encoding="utf-8")
        (fixture_tests / "test_smoke.py").write_text(textwrap.dedent("""\
            import site
            import sys
            import unittest
            from tests import support

            class IsolationSmokeTests(unittest.TestCase):
                def test_python_is_isolated(self):
                    self.assertTrue(sys.flags.isolated)
                    self.assertTrue(sys.dont_write_bytecode)
                    self.assertFalse(site.ENABLE_USER_SITE)
                    self.assertEqual(support.MARKER, 'fixture')
        """), encoding="utf-8")

        poison = self.home / "poison"
        poison.mkdir()
        (poison / "sitecustomize.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "Path(os.environ['HOME'], 'sitecustomize-trap').write_text('executed')\n",
            encoding="utf-8",
        )
        (poison / "requests.py").write_text(
            "raise RuntimeError('user Python path was imported')\n", encoding="utf-8"
        )
        self.environment = dict(
            os.environ,
            HOME=str(self.home),
            XDG_CACHE_HOME=str(self.cache),
            ICAL_TOOL_PYTHON=sys.executable,
            TEST_CACHED_VENV=str(self.venv),
            PYTHONPATH=str(poison),
            PYTHONUSERBASE=str(self.home / "user-packages"),
            PYTHONPYCACHEPREFIX=str(self.home / "bytecode"),
            PYTHONDONTWRITEBYTECODE="0",
            PYTHONNOUSERSITE="0",
            PYTHONHOME=str(self.home / "missing-python-home"),
            TZ="UTC",
        )

    def run_without_pollution(self, launcher, content=None):
        directories = (self.project, self.home, self.work)
        before = {directory: snapshot(directory) for directory in directories}

        result = subprocess.run(
            [str(self.project / launcher)],
            input=content,
            capture_output=True,
            cwd=self.work,
            env=self.environment,
            timeout=15,
        )

        for directory in directories:
            self.assertEqual(snapshot(directory), before[directory], str(directory))
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result

    def test_application_keeps_source_home_and_working_directory_unchanged(self):
        content = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Isolation test//EN\r\n"
            b"BEGIN:VEVENT\r\nUID:isolation-event\r\nSUMMARY:Original\r\n"
            b"END:VEVENT\r\nEND:VCALENDAR\r\n"
        )

        result = self.run_without_pollution("ical-tool", content=content)

        events = Calendar.from_ical(result.stdout).walk("VEVENT")
        self.assertEqual(len(events), 1)
        self.assertEqual(str(events[0]["UID"]), "isolation-event")
        self.assertEqual(str(events[0]["SUMMARY"]), "Original")
        self.assertIn(b"Kept        : 1", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_test_runner_keeps_source_home_and_working_directory_unchanged(self):
        result = self.run_without_pollution("run-tests")

        self.assertEqual(result.stdout, b"")
        self.assertIn(b"Ran 1 test", result.stderr)
        self.assertIn(b"OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
