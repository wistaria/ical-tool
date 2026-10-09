"""Shared fixtures and module loading for tests."""

import importlib.util
from pathlib import Path

from icalendar import Calendar, Event


TOOL_PATH = Path(__file__).resolve().parents[1] / "ical-tool.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("ical_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_calendar(uid="event", start=None, summary="Original", extra_properties=()):
    calendar = Calendar()
    calendar.add("VERSION", "2.0")
    calendar.add("PRODID", "-//ical-tool tests//EN")
    event = Event()
    event.add("UID", uid)
    if start is not None:
        event.add("DTSTART", start)
    if summary is not None:
        event.add("SUMMARY", summary)
    for prop, value in extra_properties:
        event.add(prop, value)
    calendar.add_component(event)
    return calendar.to_ical()
