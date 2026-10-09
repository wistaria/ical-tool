"""Cache location and environment preparation without installing packages."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_environment():
    spec = importlib.util.spec_from_file_location(
        "ical_tool_environment_tests", REPO_ROOT / "_ical_tool_env.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CacheDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.environment = load_environment()
        self.home = Path("/isolated-home")
        self.addCleanup(patch.stopall)
        patch.object(Path, "home", return_value=self.home).start()
        patch.dict(os.environ, {}, clear=True).start()

    def test_absolute_xdg_cache_home_takes_precedence(self):
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform), patch.object(
                self.environment.sys, "platform", platform
            ), patch.dict(os.environ, {"XDG_CACHE_HOME": "/custom-cache 日本語"}):
                self.assertEqual(
                    self.environment.cache_directory(), Path("/custom-cache 日本語")
                )

    def test_macos_uses_library_caches(self):
        with patch.object(self.environment.sys, "platform", "darwin"):
            self.assertEqual(
                self.environment.cache_directory(), self.home / "Library" / "Caches"
            )

    def test_unix_uses_user_cache_and_ignores_relative_xdg_path(self):
        for xdg in (None, "", "relative/cache"):
            with self.subTest(xdg=xdg), patch.object(
                self.environment.sys, "platform", "linux"
            ), patch.dict(os.environ, {} if xdg is None else {"XDG_CACHE_HOME": xdg}):
                self.assertEqual(
                    self.environment.cache_directory(), self.home / ".cache"
                )


class EnvironmentPreparationTests(unittest.TestCase):
    def setUp(self):
        self.environment = load_environment()
        temporary = tempfile.TemporaryDirectory(prefix="ical-tool-environment-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project space 日本語"
        self.project.mkdir()
        self.requirements = self.project / "requirements.txt"
        self.requirements.write_bytes(b"icalendar\npython-dateutil\nrequests\n")
        self.cache = self.root / "cache"
        cache_patch = patch.object(
            self.environment, "cache_directory", return_value=self.cache
        )
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.calls = []
        run_patch = patch.object(
            self.environment.subprocess, "run", side_effect=self.fake_run
        )
        run_patch.start()
        self.addCleanup(run_patch.stop)
        self.fail_install = False

    def fake_run(self, command, **kwargs):
        args = [str(arg) for arg in command]
        self.calls.append((args, kwargs))
        if "venv" in args:
            directory = Path(args[-1])
            (directory / "bin").mkdir(parents=True)
            python = directory / "bin" / "python"
            python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python.chmod(0o755)
        elif "install" in args and self.fail_install:
            raise subprocess.CalledProcessError(1, args)
        else:
            self.assertIn("install", args)
        return subprocess.CompletedProcess(args, 0)

    def expected_environment(self):
        key = self.environment.environment_key(
            self.project, self.requirements.read_bytes()
        )
        return self.cache / "ical-tool" / "venvs" / key

    def assert_setup_preserves_stdio(self):
        for _, kwargs in self.calls:
            self.assertTrue(kwargs["check"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["stdout"], sys.stderr)
            self.assertEqual(kwargs["cwd"], self.cache / "ical-tool")
            self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
            self.assertEqual(kwargs["env"]["PYTHONNOUSERSITE"], "1")
            self.assertEqual(kwargs["env"]["PIP_CONFIG_FILE"], os.devnull)

    def test_creates_environment_with_uv_and_snapshots_requirements(self):
        directory = self.expected_environment()

        result = self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertEqual(result, directory)
        self.assertEqual(len(self.calls), 2)
        creation, installation = (call[0] for call in self.calls)
        self.assertEqual(creation, [
            "/tools/uv", "venv", "--no-project", "--no-config",
            "--no-python-downloads", "--cache-dir", str(self.cache / "ical-tool" / "uv"),
            "--python", str(Path(sys.executable).resolve()), str(directory),
        ])
        snapshot = directory / ".ical-tool-requirements.txt"
        self.assertEqual(snapshot.read_bytes(), self.requirements.read_bytes())
        self.assertEqual(installation, [
            "/tools/uv", "pip", "install", "--no-config", "--no-python-downloads",
            "--cache-dir", str(self.cache / "ical-tool" / "uv"),
            "--python", str(result / "bin" / "python"), "-r", str(snapshot),
        ])
        self.assertTrue((directory / ".ical-tool-ready").is_file())
        self.assert_setup_preserves_stdio()

    def test_creates_environment_with_python_venv_without_uv(self):
        directory = self.expected_environment()

        result = self.environment.prepare_environment(self.project, uv=None)

        self.assertEqual(result, directory)
        self.assertEqual(len(self.calls), 2)
        creation, installation = (call[0] for call in self.calls)
        self.assertEqual(Path(creation[0]).resolve(), Path(sys.executable).resolve())
        self.assertEqual(creation[1:], ["-I", "-B", "-m", "venv", str(directory)])
        self.assertEqual(installation, [
            str(result / "bin" / "python"), "-I", "-B", "-m", "pip", "--isolated",
            "--disable-pip-version-check", "install", "--cache-dir",
            str(self.cache / "ical-tool" / "pip"),
            "-r", str(directory / ".ical-tool-requirements.txt"),
        ])
        self.assert_setup_preserves_stdio()

    def test_installers_ignore_user_python_and_pip_settings(self):
        unsafe_settings = {
            "PYTHONPATH": "/user/python-path",
            "PYTHONHOME": "/user/python-home",
            "PYTHONPYCACHEPREFIX": "/user/bytecode",
            "PYTHONDONTWRITEBYTECODE": "0",
            "PYTHONNOUSERSITE": "0",
            "PIP_TARGET": "/user/packages",
            "PIP_PREFIX": "/user/prefix",
            "PIP_USER": "1",
            "PIP_CONFIG_FILE": "/user/pip.conf",
            "UV_CONFIG_FILE": "/user/uv.toml",
            "UV_SYSTEM_PYTHON": "1",
            "HOME": "/user/home",
            "PATH": "/usr/bin",
        }
        expected_settings = {
            "HOME": "/user/home",
            "PATH": "/usr/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_CONFIG_FILE": os.devnull,
        }
        for uv in ("/tools/uv", None):
            key = "uv-isolation" if uv else "venv-isolation"
            with self.subTest(uv=uv), patch.dict(
                os.environ, unsafe_settings, clear=True
            ), patch.object(self.environment, "environment_key", return_value=key):
                parent_environment = dict(os.environ)
                self.calls.clear()

                self.environment.prepare_environment(self.project, uv=uv)

                self.assertEqual(dict(os.environ), parent_environment)
                self.assertEqual(len(self.calls), 2)
                for _, kwargs in self.calls:
                    self.assertEqual(kwargs["env"], expected_settings)
                self.assert_setup_preserves_stdio()

    def test_environment_setup_only_writes_to_the_cache(self):
        source = self.project / "ical-tool.py"
        source.write_text("print('source remains unchanged')\n", encoding="utf-8")
        original = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }

        directory = self.environment.prepare_environment(self.project, uv="/tools/uv")

        after = {
            path.relative_to(self.project): path.read_bytes()
            for path in self.project.rglob("*") if path.is_file()
        }
        self.assertEqual(after, original)
        self.assertEqual(sorted(self.root.iterdir()), sorted((self.project, self.cache)))
        self.assertTrue(directory.is_relative_to(self.cache))

    def test_cache_inside_source_tree_is_rejected_before_any_writes(self):
        linked_cache = self.root / "linked-cache"
        linked_cache.symlink_to(self.project, target_is_directory=True)
        before = sorted(self.project.rglob("*"))
        for cache in (self.project / "cache", linked_cache):
            with self.subTest(cache=cache), patch.object(
                self.environment, "cache_directory", return_value=cache
            ):
                with self.assertRaisesRegex(OSError, "outside the source tree"):
                    self.environment.prepare_environment(self.project, uv="/tools/uv")
                self.assertEqual(sorted(self.project.rglob("*")), before)
                self.assertEqual(self.calls, [])

    def test_reuses_completed_environment_without_setup_commands(self):
        first = self.environment.prepare_environment(self.project, uv="/tools/uv")
        self.calls.clear()

        second = self.environment.prepare_environment(self.project, uv=None)

        self.assertEqual(second, first)
        self.assertEqual(self.calls, [])

    def test_requirements_changes_and_package_removal_get_fresh_environments(self):
        first = self.environment.prepare_environment(self.project, uv="/tools/uv")
        self.requirements.write_bytes(b"icalendar\npython-dateutil\nrequests\nnew-package\n")
        second = self.environment.prepare_environment(self.project, uv="/tools/uv")
        self.requirements.write_bytes(b"icalendar\n")
        third = self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertEqual(len({first, second, third}), 3)
        self.assertEqual(len(self.calls), 6)
        self.assertEqual(
            (third / ".ical-tool-requirements.txt").read_bytes(),
            b"icalendar\n",
        )
        self.assertTrue((first / "bin" / "python").is_file())

    def test_python_version_change_gets_a_fresh_environment(self):
        first = self.environment.prepare_environment(self.project, uv="/tools/uv")

        with patch.object(self.environment.sys, "version", sys.version + " updated"):
            second = self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertNotEqual(first, second)
        self.assertEqual(len(self.calls), 4)

    def test_python_executable_update_changes_environment_key(self):
        executable = self.root / "base-python"
        executable.write_bytes(b"first interpreter")
        with patch.object(self.environment.sys, "executable", str(executable)):
            original = self.environment.environment_key(
                self.project, self.requirements.read_bytes()
            )
            previous_stat = executable.stat()
            executable.write_bytes(b"a new interpreter with a different size")
            os.utime(
                executable,
                ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000),
            )
            updated = self.environment.environment_key(
                self.project, self.requirements.read_bytes()
            )

        self.assertNotEqual(original, updated)

    def test_failed_install_is_not_reused_and_is_rebuilt_on_retry(self):
        directory = self.expected_environment()
        self.fail_install = True

        with self.assertRaises(subprocess.CalledProcessError):
            self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertFalse((directory / ".ical-tool-ready").exists())
        leftover = directory / "incomplete-install.txt"
        leftover.write_text("partial setup", encoding="utf-8")
        self.fail_install = False
        result = self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertEqual(result, directory)
        self.assertEqual(len(self.calls), 4)
        self.assertFalse(leftover.exists())
        self.assertTrue((directory / ".ical-tool-ready").is_file())

    def test_missing_python_in_ready_environment_triggers_rebuild(self):
        first = self.environment.prepare_environment(self.project, uv="/tools/uv")
        (first / "bin" / "python").unlink()
        self.calls.clear()

        second = self.environment.prepare_environment(self.project, uv="/tools/uv")

        self.assertEqual(first, second)
        self.assertTrue((second / "bin" / "python").is_file())
        self.assertEqual(len(self.calls), 2)


if __name__ == "__main__":
    unittest.main()
