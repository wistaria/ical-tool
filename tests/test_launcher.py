import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]

FAKE_UV = textwrap.dedent("""\
    import json
    import os
    import sys

    with open(os.environ['TEST_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['uv'] + sys.argv[1:]) + '\\n')
    if sys.argv[1:] != ['python', 'find', '--system', '--no-project',
                       '--no-config', '--no-python-downloads', '--no-cache']:
        raise RuntimeError('Unexpected uv command: ' + repr(sys.argv))
    print(os.environ['FAKE_BASE_PYTHON'])
    """)

FAKE_BASE_PYTHON = textwrap.dedent("""\
    import json
    import os
    import sys

    with open(os.environ['TEST_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['base-python'] + sys.argv[1:]) + '\\n')
    with open(os.environ['TEST_ENV_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['base-python', os.environ.get('PYTHONDONTWRITEBYTECODE'),
                              os.environ.get('PYTHONNOUSERSITE')]) + '\\n')
    print('environment setup log', file=sys.stderr)
    print(os.environ['TEST_VENV'])
    """)

FAKE_VENV_PYTHON = textwrap.dedent("""\
    import json
    import os
    import sys

    with open(os.environ['TEST_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['venv-python'] + sys.argv[1:]) + '\\n')
    with open(os.environ['TEST_ENV_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['venv-python', os.environ.get('PYTHONDONTWRITEBYTECODE'),
                              os.environ.get('PYTHONNOUSERSITE')]) + '\\n')
    sys.stdout.write(sys.stdin.read())
    sys.exit(int(os.environ.get('RUN_EXIT', '0')))
    """)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ical-tool-launcher-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / 'repo space 日本語'
        self.app.mkdir()
        self.venv = self.root / 'isolated venv 日本語'
        self.launcher = self.app / 'ical-tool'
        shutil.copyfile(REPO_ROOT / 'ical-tool', self.launcher)
        for filename in ('ical-tool.py', 'requirements.txt', '_ical_tool_env.py',
                         '_ical_tool_env.sh', 'run-tests'):
            shutil.copyfile(REPO_ROOT / filename, self.app / filename)
        self.test_runner = self.app / 'run-tests'

        self.fakebin = self.root / 'fake-bin'
        self.fakebin.mkdir()
        self.bash = shutil.which('bash')
        dirname = shutil.which('dirname')
        self.assertIsNotNone(self.bash)
        self.assertIsNotNone(dirname)
        (self.fakebin / 'dirname').symlink_to(dirname)
        self.base_python = self.root / 'fake base python'
        self.make_python(self.base_python, FAKE_BASE_PYTHON)
        (self.fakebin / 'python3').symlink_to(self.base_python)
        (self.venv / 'bin').mkdir(parents=True)
        self.make_python(self.venv / 'bin' / 'python', FAKE_VENV_PYTHON)
        self.log = self.root / 'calls.jsonl'
        self.env_log = self.root / 'environment.jsonl'
        self.env = dict(
            os.environ,
            PATH=str(self.fakebin),
            TEST_LOG=str(self.log),
            TEST_ENV_LOG=str(self.env_log),
            FAKE_BASE_PYTHON=str(self.base_python),
            TEST_VENV=str(self.venv),
            PYTHONDONTWRITEBYTECODE='0',
            PYTHONNOUSERSITE='0',
        )
        self.env.pop('ICAL_TOOL_PYTHON', None)

    @staticmethod
    def make_python(path, body):
        sidecar = Path(str(path) + '.py')
        sidecar.write_text(body, encoding='utf-8')
        path.write_text(
            '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -I -B '
            + shlex.quote(str(sidecar)) + ' "$@"\n',
            encoding='utf-8',
        )
        path.chmod(0o755)

    def run_launcher(self, *args, stdin='calendar output\n'):
        return self.run_script(self.launcher, *args, stdin=stdin)

    def run_script(self, script, *args, stdin='calendar output\n'):
        result = subprocess.run(
            [self.bash, str(script), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            input=stdin,
            text=True,
            encoding='utf-8',
            timeout=10,
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, calls

    def assert_calendar_output(self, result):
        self.assertEqual(result.stdout, 'calendar output\n')

    def test_selects_system_python_with_uv(self):
        self.make_python(self.fakebin / 'uv', FAKE_UV)

        result, calls = self.run_launcher('--input=input.ics')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calendar_output(result)
        self.assertEqual(result.stderr, 'environment setup log\n')
        self.assertEqual(calls, [
            ['uv', 'python', 'find', '--system', '--no-project', '--no-config',
             '--no-python-downloads', '--no-cache'],
            ['base-python', '-I', '-B', str(self.app / '_ical_tool_env.py'), str(self.app),
             str(self.fakebin / 'uv')],
            ['venv-python', '-I', '-B', str(self.app / 'ical-tool.py'), '--input=input.ics'],
        ])

    def test_falls_back_to_python3_without_uv(self):
        result, calls = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calendar_output(result)
        self.assertEqual(result.stderr, 'environment setup log\n')
        self.assertEqual(calls, [
            ['base-python', '-I', '-B', str(self.app / '_ical_tool_env.py'), str(self.app), ''],
            ['venv-python', '-I', '-B', str(self.app / 'ical-tool.py')],
        ])

    def test_preserves_arguments_stdin_and_exit_code(self):
        self.make_python(self.fakebin / 'uv', FAKE_UV)
        self.env['RUN_EXIT'] = '23'
        args = ['--input=input with spaces.ics', '--replace-prop=SUMMARY=予定 あり',
                '', '$literal', 'line\nbreak']

        stdin = 'BEGIN:VCALENDAR\n予定の入力\nEND:VCALENDAR\n'
        result, calls = self.run_launcher(*args, stdin=stdin)

        self.assertEqual(result.returncode, 23)
        self.assertEqual(result.stdout, stdin)
        self.assertEqual(result.stderr, 'environment setup log\n')
        self.assertEqual(calls[-1], ['venv-python', '-I', '-B', str(self.app / 'ical-tool.py'), *args])

    def test_test_runner_shares_environment_and_preserves_options_and_exit_code(self):
        self.make_python(self.fakebin / 'uv', FAKE_UV)
        cli_result, cli_calls = self.run_launcher()
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)
        self.env['RUN_EXIT'] = '17'
        args = ['--pattern=test_calendar*.py', '--failfast']

        result, calls = self.run_script(self.test_runner, *args, stdin='test output\n')

        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, 'test output\n')
        self.assertEqual(result.stderr, 'environment setup log\n')
        # Both entry points ask the shared helper for the same repository and
        # installer, then execute the returned cached Python.
        self.assertEqual(calls[len(cli_calls) + 1], cli_calls[1])
        self.assertEqual(calls[-1], [
            'venv-python', '-I', '-B', '-m', 'unittest', 'discover', '-s', str(self.app / 'tests'),
            '-t', str(self.app), '-v', *args,
        ])

    def test_test_runner_falls_back_to_python3_without_uv(self):
        result, calls = self.run_script(self.test_runner)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calendar_output(result)
        self.assertEqual(calls, [
            ['base-python', '-I', '-B', str(self.app / '_ical_tool_env.py'), str(self.app), ''],
            ['venv-python', '-I', '-B', '-m', 'unittest', 'discover', '-s', str(self.app / 'tests'),
             '-t', str(self.app), '-v'],
        ])

    def test_specified_python_takes_priority_while_retaining_uv_installer(self):
        self.make_python(self.fakebin / 'uv', FAKE_UV)
        specified_python = self.root / 'specified base python'
        self.make_python(
            specified_python,
            FAKE_BASE_PYTHON.replace("'base-python'", "'specified-python'"),
        )
        self.env['ICAL_TOOL_PYTHON'] = str(specified_python)

        result, calls = self.run_script(self.test_runner)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            ['specified-python', '-I', '-B', str(self.app / '_ical_tool_env.py'), str(self.app),
             str(self.fakebin / 'uv')],
            ['venv-python', '-I', '-B', '-m', 'unittest', 'discover', '-s', str(self.app / 'tests'),
             '-t', str(self.app), '-v'],
        ])

    def test_overrides_bytecode_and_user_site_settings_for_both_entry_points(self):
        cli_result, _ = self.run_launcher()
        test_result, _ = self.run_script(self.test_runner)

        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)
        self.assertEqual(test_result.returncode, 0, test_result.stderr)
        environments = [json.loads(line) for line in self.env_log.read_text().splitlines()]
        self.assertEqual(environments, [
            ['base-python', '1', '1'], ['venv-python', '1', '1'],
            ['base-python', '1', '1'], ['venv-python', '1', '1'],
        ])


if __name__ == '__main__':
    unittest.main()
