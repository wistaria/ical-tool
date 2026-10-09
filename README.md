# ical-tool

[English](README.md) | [日本語](README-ja.md)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Author](https://img.shields.io/badge/author-Synge%20Todo-blue)](https://github.com/wistaria)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Useful scripts for ical manipulation

## Usage

```sh
./ical-tool --input=https://example.com/calendar.ics --output=output.ics
```

The launcher stores virtual environments outside the project, under
`~/Library/Caches/ical-tool/venvs/` on macOS or `~/.cache/ical-tool/venvs/` on Linux.
An absolute `XDG_CACHE_HOME` overrides the cache directory on either OS;
the cache must be outside the source tree.

Environments are identified by the project's location, the Python interpreter
and its version, and the contents of `requirements.txt`. Unchanged environments
are reused; changes create a new environment and reinstall dependencies. Older
environments remain in the cache. Failed installations are retried on the next
launch, and concurrent launches share an initialization lock.

When `uv` is available, it selects the Python interpreter and creates and installs
the environment. Otherwise, the launcher uses `python3 -m venv` and `pip`.
Set `ICAL_TOOL_PYTHON` to an interpreter path to use a specific Python version.

The launcher and test runner disable bytecode writes, so they do not create
`__pycache__` or `.pyc` files in the source tree. Python runs in isolated mode,
and dependencies and installer caches stay in the cache directory. Installation
ignores pip and uv configuration files, and Python is never downloaded
automatically. The existing Python environment and shell configuration are
left unchanged; ICS files are written only to the requested output.

`--input` accepts an HTTP/HTTPS URL or a local filename and can be repeated to
merge multiple inputs into one calendar. The first calendar's properties are
retained, and components from all inputs are included. Identical timezone
definitions are merged; conflicting definitions with the same `TZID` are rejected.

When `--input` is omitted, ICS data is read from standard input. When `--output`
is omitted, ICS data is written to standard output. `-` can also be used explicitly
for standard input or output. Diagnostic and setup messages go to standard error.

```sh
./ical-tool --input=first.ics --input=second.ics --output=merged.ics
./ical-tool --remove-prop=LOCATION < input.ics > output.ics
./ical-tool --input=calendar.ics > output.ics
```

Event properties are removed or replaced only when explicitly requested.

All entries are kept when `--days` is omitted. When specified, the cutoff is local
midnight that many days ago, using the execution environment's time zone. Events
without an occurrence on or after the cutoff are removed. `--days=0` keeps events
with an occurrence today or later. Negative values are not accepted.

Use `--remove-prop` to choose the properties to remove and `--replace-prop` to
specify a property name and replacement text:

```sh
./ical-tool --input=https://example.com/calendar.ics --output=output.ics \
  --days=30 \
  --remove-prop=LOCATION --remove-prop=DESCRIPTION \
  --replace-prop="SUMMARY=Busy" --replace-prop="ORGANIZER=mailto:busy@example.com"
```

`--remove-prop` can be repeated. When specified, only the listed properties are
removed. `--replace-prop` can also be repeated; when specified, only the listed
properties are replaced. Without these options, event properties (including
`SUMMARY`) are preserved. Property names are case-insensitive.

Replacements are applied after removals, and missing properties are added. If
the same property is specified multiple times, the last value wins. Values can
be empty or contain `=`. `--summary="Busy"` remains available as a shortcut for
`--replace-prop="SUMMARY=Busy"` and follows the same ordering rules.
For non-text properties, use iCalendar values, for example
`--replace-prop="DTSTART=20261231T120000Z"` or `--replace-prop="GEO=35.0;139.0"`.
Alarms are removed in all cases.

## Tests

The test runner uses the same cached virtual environment as `ical-tool` and
installs `requirements.txt` automatically when needed:

```sh
./run-tests
./run-tests -p test_cli.py
```

GitHub Actions invokes `./run-tests` with Python 3.11 and 3.14 for pushes and pull
requests, using the cached environment for each interpreter. The workflow can
also be started manually from the Actions tab.
