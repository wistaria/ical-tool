import argparse
import unittest
from datetime import date, datetime, timedelta, timezone

from dateutil.tz import gettz
from icalendar import Alarm, Event

from tests.helpers import load_tool


class EventProcessingTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tool.TZ = gettz("America/New_York")

    def make_event(self, start=None):
        event = Event()
        event.add("UID", "event")
        event.add("SUMMARY", "Original")
        if start is not None:
            event.add("DTSTART", start)
        return event

    def test_cutoff_includes_boundary_for_dates_and_datetimes(self):
        cutoff = datetime(2025, 3, 10, tzinfo=self.tool.TZ)
        cases = [
            (None, False),
            (date(2025, 3, 9), False),
            (date(2025, 3, 10), True),
            (datetime(2025, 3, 9, 23, 59, 59), False),
            (datetime(2025, 3, 10), True),
            (datetime(2025, 3, 10, 3, 59, 59, tzinfo=timezone.utc), False),
            (datetime(2025, 3, 10, 4, tzinfo=timezone.utc), True),
            (datetime(2025, 3, 11, tzinfo=timezone.utc), True),
        ]
        for start, expected in cases:
            with self.subTest(start=start):
                self.assertEqual(
                    self.tool.has_future_occurrence(self.make_event(start), cutoff),
                    expected,
                )

        # Local midnight must use the offset for that date across the DST change.
        self.assertEqual(
            self.tool.event_start(self.make_event(date(2025, 3, 9))).utcoffset(),
            timedelta(hours=-5),
        )
        self.assertEqual(
            self.tool.event_start(self.make_event(date(2025, 3, 10))).utcoffset(),
            timedelta(hours=-4),
        )

    def test_rrule_keeps_future_occurrences_and_excludes_finished_series(self):
        self.tool.TZ = timezone.utc
        cutoff = datetime(2025, 1, 10, tzinfo=timezone.utc)
        cases = [
            ({"freq": "DAILY", "count": 9}, False),
            ({"freq": "DAILY", "count": 10}, True),
            ({"freq": "DAILY"}, True),
            ({"freq": "DAILY", "until": cutoff - timedelta(seconds=1)}, False),
            ({"freq": "DAILY", "until": cutoff}, True),
        ]
        for rule, expected in cases:
            with self.subTest(rule=rule):
                event = self.make_event(datetime(2025, 1, 1, tzinfo=timezone.utc))
                event.add("RRULE", rule)
                self.assertEqual(self.tool.has_future_occurrence(event, cutoff), expected)

    def test_rdate_checks_all_values_and_repeated_properties(self):
        cutoff = datetime(2025, 3, 10, tzinfo=self.tool.TZ)
        cases = [
            ([[date(2025, 3, 9)]], False),
            ([[date(2025, 3, 10)]], True),
            ([[datetime(2025, 3, 10)]], True),
            ([[datetime(2025, 3, 10, 4, tzinfo=timezone.utc)]], True),
            ([[date(2025, 3, 8), date(2025, 3, 11)]], True),
            ([[date(2025, 3, 8)], [date(2025, 3, 10)]], True),
        ]
        for groups, expected in cases:
            with self.subTest(rdates=groups):
                event = self.make_event(date(2025, 3, 1))
                for values in groups:
                    event.add("RDATE", values)
                self.assertEqual(self.tool.has_future_occurrence(event, cutoff), expected)

    def test_anonymize_preserves_properties_by_default_and_removes_all_alarms(self):
        event = self.make_event(date(2025, 1, 1))
        event.add("LOCATION", "Meeting room")
        event.add("DESCRIPTION", "Private details")
        event.add("ATTENDEE", "mailto:one@example.com")
        event.add("ATTENDEE", "mailto:two@example.com")
        for minutes in (15, 30):
            alarm = Alarm()
            alarm.add("ACTION", "DISPLAY")
            alarm.add("DESCRIPTION", "Reminder")
            alarm.add("TRIGGER", timedelta(minutes=-minutes))
            event.add_component(alarm)
        original_properties = list(event.items())

        self.tool.anonymize(event)

        self.assertEqual(list(event.items()), original_properties)
        self.assertEqual(event.subcomponents, [])

    def test_selected_removal_deletes_every_attendee_and_preserves_other_fields(self):
        event = self.make_event()
        event.add("ATTENDEE", "mailto:one@example.com")
        event.add("ATTENDEE", "mailto:two@example.com")
        event.add("DESCRIPTION", "Private details")
        event.add("LOCATION", "Meeting room")

        self.tool.anonymize(event, remove_props=("ATTENDEE", "DESCRIPTION", "X-MISSING"))

        self.assertNotIn("ATTENDEE", event)
        self.assertNotIn("DESCRIPTION", event)
        self.assertEqual(str(event["SUMMARY"]), "Original")
        self.assertEqual(str(event["LOCATION"]), "Meeting room")
        self.assertEqual(str(event["UID"]), "event")

    def test_replacements_run_after_removal_and_last_value_wins(self):
        event = self.make_event()
        event.add("LOCATION", "Private room")
        event.add("DESCRIPTION", "Private details")

        self.tool.anonymize(
            event,
            remove_props=("SUMMARY", "LOCATION", "DESCRIPTION"),
            replace_props=(
                ("SUMMARY", "First"),
                ("LOCATION", "Public room"),
                ("SUMMARY", "予定あり"),
                ("X-STATUS", "Busy"),
            ),
        )

        self.assertEqual(str(event["SUMMARY"]), "予定あり")
        self.assertEqual(str(event["LOCATION"]), "Public room")
        self.assertEqual(str(event["X-STATUS"]), "Busy")
        self.assertNotIn("DESCRIPTION", event)

    def test_parse_replacement_preserves_text_values(self):
        cases = [
            ("summary=予定あり", ("SUMMARY", "予定あり")),
            ("  location  =非公開", ("LOCATION", "非公開")),
            ("SUMMARY=", ("SUMMARY", "")),
            ("DESCRIPTION=a=b==c", ("DESCRIPTION", "a=b==c")),
            ("SUMMARY=  spaced  ", ("SUMMARY", "  spaced  ")),
        ]
        for argument, expected in cases:
            with self.subTest(argument=argument):
                self.assertEqual(self.tool.parse_replacement(argument), expected)

    def test_parse_replacement_converts_typed_values_and_serializes_them(self):
        cases = [
            ("DTSTART=20261009T120000Z", datetime(2026, 10, 9, 12, tzinfo=timezone.utc)),
            ("DTSTART=20261009", date(2026, 10, 9)),
            ("GEO=35.68;139.76", (35.68, 139.76)),
        ]
        for argument, expected in cases:
            with self.subTest(argument=argument):
                prop, value = self.tool.parse_replacement(argument)
                self.assertEqual(value, expected)
                event = self.make_event()
                self.tool.anonymize(event, replace_props=((prop, value),))
                reparsed = Event.from_ical(event.to_ical())
                serialized = reparsed[prop].to_ical()
                if isinstance(serialized, bytes):
                    serialized = serialized.decode()
                self.assertEqual(serialized, argument.partition("=")[2])

    def test_parse_replacement_rejects_invalid_format_and_typed_values(self):
        for argument in ("", "SUMMARY", "=value", "   =value", "DTSTART=invalid", "GEO=invalid"):
            with self.subTest(argument=argument):
                with self.assertRaises(argparse.ArgumentTypeError):
                    self.tool.parse_replacement(argument)


if __name__ == "__main__":
    unittest.main()
