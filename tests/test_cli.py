"""Exercise the command line with local calendars and mocked HTTP responses."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from icalendar import Calendar, Todo

from tests.helpers import TOOL_PATH, load_tool, make_calendar


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments, content=None):
        environment = dict(os.environ, TZ="UTC")
        return subprocess.run(
            [sys.executable, "-I", "-B", str(TOOL_PATH), *arguments],
            input=content,
            capture_output=True,
            env=environment,
            cwd=TOOL_PATH.parent,
            timeout=15,
        )

    def read_output(self, content):
        calendars = Calendar.from_ical(content, multiple=True)
        self.assertEqual(len(calendars), 1)
        self.assertEqual(calendars[0].name, "VCALENDAR")
        return calendars[0]

    def test_standard_streams_and_explicit_dash(self):
        content = make_calendar(
            summary="会議",
            extra_properties=(("LOCATION", "会議室"), ("DESCRIPTION", "Notes")),
        )
        for arguments in ((), ("--input=-", "--output=-")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments, content=content)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertTrue(result.stdout.startswith(b"BEGIN:VCALENDAR\r\n"))
                self.assertTrue(result.stdout.endswith(b"END:VCALENDAR\r\n"))
                self.assertNotIn(b"Cutoff date", result.stdout)
                event = self.read_output(result.stdout).walk("VEVENT")[0]
                self.assertEqual(str(event["SUMMARY"]), "会議")
                self.assertEqual(str(event["LOCATION"]), "会議室")
                self.assertEqual(str(event["DESCRIPTION"]), "Notes")
                self.assertIn(b"Cutoff date : none", result.stderr)
                self.assertIn(b"Kept        : 1", result.stderr)
                self.assertIn(b"Removed     : 0", result.stderr)
                self.assertIn(b"Output      : stdout", result.stderr)

    def test_local_input_and_output_with_spaces_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "入力 カレンダー.ics"
            target = Path(directory) / "出力 カレンダー.ics"
            source.write_bytes(make_calendar(uid="local", summary="予定あり"))

            result = self.run_cli("--input", str(source), "--output", str(target))

            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout, b"")
            event = self.read_output(target.read_bytes()).walk("VEVENT")[0]
            self.assertEqual(str(event["UID"]), "local")
            self.assertEqual(str(event["SUMMARY"]), "予定あり")
            self.assertIn(str(target).encode(), result.stderr)

    def test_multiple_inputs_keep_first_headers_and_non_event_components(self):
        first = Calendar.from_ical(make_calendar(uid="first"))
        first["PRODID"] = "-//First calendar//EN"
        first.add("X-WR-CALNAME", "First")
        task = Todo()
        task.add("UID", "todo")
        task.add("SUMMARY", "Keep task summary")
        task.add("LOCATION", "Keep task location")
        first.add_component(task)

        second = Calendar.from_ical(make_calendar(uid="second"))
        second["PRODID"] = "-//Second calendar//EN"
        second.add("X-WR-CALNAME", "Second")

        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.ics"
            second_path = Path(directory) / "second.ics"
            first_path.write_bytes(first.to_ical())
            # A single input may itself contain multiple VCALENDARs.
            second_path.write_bytes(second.to_ical() + make_calendar(uid="third"))

            result = self.run_cli(
                "--input", str(first_path), "--input", str(second_path),
                "--replace-prop=SUMMARY=Busy", "--remove-prop=LOCATION",
            )

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        calendar = self.read_output(result.stdout)
        self.assertEqual(str(calendar["PRODID"]), "-//First calendar//EN")
        self.assertEqual(str(calendar["X-WR-CALNAME"]), "First")
        events = calendar.walk("VEVENT")
        self.assertEqual({str(event["UID"]) for event in events}, {"first", "second", "third"})
        self.assertTrue(all(str(event["SUMMARY"]) == "Busy" for event in events))
        tasks = calendar.walk("VTODO")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(str(tasks[0]["SUMMARY"]), "Keep task summary")
        self.assertEqual(str(tasks[0]["LOCATION"]), "Keep task location")
        self.assertIn(b"Kept        : 3", result.stderr)

    def test_url_and_local_file_are_merged_without_real_network(self):
        tool = load_tool()
        response = mock.Mock(content=make_calendar(uid="remote"))
        binary_output = io.BytesIO()
        output = io.TextIOWrapper(binary_output, encoding="utf-8")
        diagnostics = io.StringIO()
        url = "https://example.invalid/calendar.ics"

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "local.ics"
            source.write_bytes(make_calendar(uid="local"))
            arguments = [str(TOOL_PATH), "--input", url, "--input", str(source)]
            with mock.patch.object(sys, "argv", arguments), \
                    mock.patch.object(sys, "stdout", output), \
                    mock.patch.object(sys, "stderr", diagnostics), \
                    mock.patch.object(tool.requests, "get", return_value=response) as get:
                tool.main()

        get.assert_called_once_with(url, timeout=30)
        response.raise_for_status.assert_called_once_with()
        events = self.read_output(binary_output.getvalue()).walk("VEVENT")
        self.assertEqual({str(event["UID"]) for event in events}, {"remote", "local"})
        self.assertIn("Kept        : 2", diagnostics.getvalue())
        output.close()

    def test_omitted_days_keeps_old_events_and_events_without_dtstart(self):
        old = make_calendar(uid="old", start=datetime(1900, 1, 1, tzinfo=timezone.utc))
        undated = Calendar.from_ical(make_calendar(uid="undated"))
        event = undated.walk("VEVENT")[0]
        if "DTSTART" in event:
            del event["DTSTART"]

        result = self.run_cli(content=old + undated.to_ical())

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        events = self.read_output(result.stdout).walk("VEVENT")
        self.assertEqual({str(event["UID"]) for event in events}, {"old", "undated"})
        self.assertIn(b"Cutoff date : none", result.stderr)
        self.assertIn(b"Removed     : 0", result.stderr)

    def test_days_zero_filters_events_and_applies_removal_and_replacement(self):
        old = make_calendar(uid="old", start=datetime(1900, 1, 1, tzinfo=timezone.utc))
        future = make_calendar(
            uid="future",
            start=datetime(2099, 1, 1, tzinfo=timezone.utc),
            extra_properties=(("LOCATION", "Private room"), ("DESCRIPTION", "Notes")),
        )

        result = self.run_cli(
            "--days=0", "--remove-prop=location", "--remove-prop=DESCRIPTION",
            "--replace-prop=summary=予定あり", "--replace-prop=X-VISIBILITY=private",
            content=old + future,
        )

        self.assertEqual(result.returncode, 0, result.stderr.decode())
        events = self.read_output(result.stdout).walk("VEVENT")
        self.assertEqual(len(events), 1)
        self.assertEqual(str(events[0]["UID"]), "future")
        self.assertEqual(str(events[0]["SUMMARY"]), "予定あり")
        self.assertEqual(str(events[0]["X-VISIBILITY"]), "private")
        self.assertNotIn("LOCATION", events[0])
        self.assertNotIn("DESCRIPTION", events[0])
        self.assertIn(b"Kept        : 1", result.stderr)
        self.assertIn(b"Removed     : 1", result.stderr)

    def test_invalid_arguments_fail_before_reading_or_downloading(self):
        cases = (
            (("--days=-1",), "--days must be non-negative"),
            (("--days=invalid",), "invalid int value"),
            (("--input=-", "--input=-"), "Standard input can only be used once"),
            (("--replace-prop=SUMMARY",), "Expected PROPERTY=VALUE"),
        )
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                tool = load_tool()
                diagnostics = io.StringIO()
                argv = [str(TOOL_PATH), "--input=https://example.invalid/calendar.ics", *arguments]
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(sys, "stderr", diagnostics), \
                        mock.patch.object(tool, "read_calendars") as read, \
                        mock.patch.object(tool.requests, "get") as get:
                    with self.assertRaises(SystemExit) as raised:
                        tool.main()
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, diagnostics.getvalue())
                read.assert_not_called()
                get.assert_not_called()

    def test_same_input_and_output_file_is_processed_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.ics"
            path.write_bytes(make_calendar(uid="same-file", summary="Original"))

            result = self.run_cli(
                "--input", str(path), "--output", str(path), "--summary=Busy",
            )

            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stdout, b"")
            event = self.read_output(path.read_bytes()).walk("VEVENT")[0]
            self.assertEqual(str(event["UID"]), "same-file")
            self.assertEqual(str(event["SUMMARY"]), "Busy")

    def test_bad_inputs_fail_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.ics"
            invalid = Path(directory) / "invalid.ics"
            invalid.write_text("This is not an iCalendar.\n", encoding="utf-8")
            for source in (missing, invalid):
                with self.subTest(source=source.name):
                    target = Path(directory) / "output.ics"
                    target.write_bytes(b"Existing output must survive")

                    result = self.run_cli("--input", str(source), "--output", str(target))

                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, b"")
                    self.assertTrue(result.stderr)
                    self.assertNotIn(b"Traceback", result.stderr)
                    self.assertEqual(target.read_bytes(), b"Existing output must survive")


if __name__ == "__main__":
    unittest.main()
