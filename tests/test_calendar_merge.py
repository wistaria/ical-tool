"""Protect timezone definitions when combining multiple calendars."""

import tempfile
import unittest
from pathlib import Path

from tests.helpers import load_tool


def calendar_with_timezone(uid, offset="+0900"):
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        f"PRODID:-//{uid}//EN\r\n"
        "BEGIN:VTIMEZONE\r\n"
        "TZID:Custom/Local\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:19700101T000000\r\n"
        f"TZOFFSETFROM:{offset}\r\n"
        f"TZOFFSETTO:{offset}\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        "DTSTART;TZID=Custom/Local:20250101T120000\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()


class CalendarMergeTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def write_calendar(self, name, content):
        path = self.directory / name
        path.write_bytes(content)
        return str(path)

    def test_identical_timezone_definitions_are_merged_without_losing_events(self):
        first = self.write_calendar("first.ics", calendar_with_timezone("first"))
        second = self.write_calendar("second.ics", calendar_with_timezone("second"))

        merged = self.tool.merge_calendars([first, second])

        self.assertEqual(len(merged.walk("VTIMEZONE")), 1)
        self.assertEqual(
            {str(event["UID"]) for event in merged.walk("VEVENT")}, {"first", "second"}
        )
        self.assertEqual(str(merged["PRODID"]), "-//first//EN")

    def test_conflicting_timezone_definitions_leave_existing_output_untouched(self):
        first = self.write_calendar("first.ics", calendar_with_timezone("first"))
        second = self.write_calendar("second.ics", calendar_with_timezone("second", "+0800"))
        original = Path(first).read_bytes()

        with self.assertRaisesRegex(ValueError, "Conflicting VTIMEZONE definitions"):
            self.tool.process_calendar([first, second], output=first)

        self.assertEqual(Path(first).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
