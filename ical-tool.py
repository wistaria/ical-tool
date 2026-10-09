
#!/usr/bin/env python3

import argparse
import sys
from datetime import datetime, date, timedelta, time
from pathlib import Path

import requests
from icalendar import Calendar
from icalendar.prop import TypesFactory, vText
from dateutil.rrule import rrulestr
from dateutil.tz import gettz, tzlocal

TZ = gettz() or tzlocal()


def normalize_datetime(dt):
    """Convert date/datetime to timezone-aware datetime."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, time.min)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)

    return dt


def event_start(event):
    """Return DTSTART as timezone-aware datetime."""
    if "DTSTART" not in event:
        return None

    return normalize_datetime(event.decoded("DTSTART"))


def has_future_occurrence(event, cutoff):
    """Check whether an event has an occurrence on/after cutoff."""
    start = event_start(event)

    if start is None:
        return False

    if start >= cutoff:
        return True

    # Check RRULE
    if "RRULE" in event:
        try:
            rule = event["RRULE"].to_ical().decode()
            rr = rrulestr(rule, dtstart=start)
            if rr.after(cutoff, inc=True) is not None:
                return True
        except (ValueError, TypeError, OverflowError):
            # Keep events whose recurrence cannot be evaluated.
            return True

    # Check RDATE
    if "RDATE" in event:
        rdates = event["RDATE"]

        if not isinstance(rdates, list):
            rdates = [rdates]

        for rdate in rdates:
            for value in rdate.dts:
                dt = normalize_datetime(value.dt)
                if dt >= cutoff:
                    return True

    return False


def anonymize(event, remove_props=(), replace_props=()):
    """Remove selected properties and alarms, replace selected properties."""

    # Remove selected properties
    for prop in remove_props:
        if prop in event:
            del event[prop]

    # Remove all VALARM subcomponents
    event.subcomponents = [
        component
        for component in event.subcomponents
        if component.name != "VALARM"
    ]

    # Replace selected properties
    for prop, value in replace_props:
        if prop in event:
            del event[prop]
        event.add(prop, value)


def read_calendars(source):
    """Read iCalendars from standard input, a URL, or a local file."""
    if source is None or source == "-":
        content = sys.stdin.buffer.read()
    elif source.lower().startswith(("http://", "https://")):
        response = requests.get(source, timeout=30)
        response.raise_for_status()
        content = response.content
    else:
        content = Path(source).read_bytes()

    calendars = Calendar.from_ical(content, multiple=True)
    if not calendars or any(calendar.name != "VCALENDAR" for calendar in calendars):
        raise ValueError(f"Input must contain a VCALENDAR: {source or 'stdin'}")
    return calendars


def merge_calendars(inputs):
    """Merge all components, retaining the first calendar's properties."""
    calendar = None
    timezones = {}
    for source in inputs or (None,):
        for incoming in read_calendars(source):
            components = incoming.subcomponents
            if calendar is None:
                calendar = incoming
                calendar.subcomponents = []

            for component in components:
                if component.name == "VTIMEZONE" and "TZID" in component:
                    tzid = str(component["TZID"])
                    definition = component.to_ical()
                    if tzid in timezones:
                        if timezones[tzid] != definition:
                            raise ValueError(f"Conflicting VTIMEZONE definitions for {tzid}")
                        continue
                    timezones[tzid] = definition
                calendar.add_component(component)
    return calendar


def process_calendar(inputs=None, output=None, remove_props=(), replace_props=(), days=None):
    """Read, merge, anonymize, filter and write iCalendars."""
    calendar = merge_calendars(inputs)

    # Calculate cutoff date only when filtering is requested
    cutoff_date = None
    cutoff = None
    if days is not None:
        today = datetime.now(TZ).date()
        cutoff_date = today - timedelta(days=days)
        cutoff = datetime.combine(cutoff_date, time.min, TZ)

    kept = 0
    removed = 0

    # Process VEVENT components
    for component in list(calendar.subcomponents):
        if component.name != "VEVENT":
            continue

        if cutoff is not None and not has_future_occurrence(component, cutoff):
            calendar.subcomponents.remove(component)
            removed += 1
            continue

        anonymize(component, remove_props=remove_props, replace_props=replace_props)
        kept += 1

    # Write ICS data separately from diagnostic output
    content = calendar.to_ical()
    if output is None or output == "-":
        sys.stdout.buffer.write(content)
    else:
        Path(output).write_bytes(content)

    print(f"Cutoff date : {cutoff_date if cutoff_date is not None else 'none'}", file=sys.stderr)
    print(f"Kept        : {kept}", file=sys.stderr)
    print(f"Removed     : {removed}", file=sys.stderr)
    print(f"Output      : {output if output not in (None, '-') else 'stdout'}", file=sys.stderr)


def parse_replacement(value):
    """Parse PROPERTY=VALUE using the property's iCalendar value type."""
    prop, separator, replacement = value.partition("=")
    if not separator or not prop.strip():
        raise argparse.ArgumentTypeError(
            "Expected PROPERTY=VALUE with a non-empty property name"
        )
    prop = prop.strip().upper()
    value_type = TypesFactory().for_property(prop)
    if value_type is not vText:
        try:
            replacement = value_type.from_ical(replacement)
        except (ValueError, TypeError) as error:
            raise argparse.ArgumentTypeError(f"Invalid value for {prop}: {error}") from error
    return prop, replacement


def main():
    parser = argparse.ArgumentParser(
        description="Read, merge, anonymize and filter iCalendar events"
    )
    parser.add_argument(
        "--input",
        dest="inputs",
        action="append",
        metavar="URL_OR_FILE",
        help=(
            "Input ICS URL (HTTP/HTTPS) or filename; repeat to merge multiple inputs. "
            "Defaults to standard input; '-' also reads standard input"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="FILE",
        help="Output ICS filename (default: standard output; '-' also writes standard output)",
    )
    parser.add_argument(
        "--remove-prop",
        dest="remove_props",
        action="append",
        type=str.upper,
        metavar="PROPERTY",
        help=(
            "Property to remove; repeat to remove multiple properties. "
            "No properties are removed by default"
        ),
    )
    parser.add_argument(
        "--replace-prop",
        dest="replace_props",
        action="append",
        type=parse_replacement,
        metavar="PROPERTY=VALUE",
        help=(
            "Property and replacement text; repeat to replace multiple properties. "
            "No properties are replaced by default. "
            "Replacements are applied after removals; the last value wins"
        ),
    )
    parser.add_argument(
        "--summary",
        dest="replace_props",
        action="append",
        type=lambda value: ("SUMMARY", value),
        metavar="TEXT",
        help="Shortcut for --replace-prop=SUMMARY=TEXT",
    )
    parser.add_argument(
        "--days",
        type=int,
        metavar="DAYS",
        help=(
            "Keep events occurring on or after local midnight DAYS days ago. "
            "When omitted, all entries are kept"
        ),
    )

    args = parser.parse_args()
    if args.days is not None and args.days < 0:
        parser.error("--days must be non-negative")
    if args.inputs and args.inputs.count("-") > 1:
        parser.error("Standard input can only be used once")
    try:
        process_calendar(
            args.inputs,
            args.output,
            remove_props=args.remove_props or (),
            replace_props=args.replace_props or (),
            days=args.days,
        )
    except (OSError, ValueError, requests.RequestException) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()

