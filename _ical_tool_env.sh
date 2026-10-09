#!/usr/bin/env bash

# These settings also reach Python subprocesses started by the tests or installers.
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
# Configuration passed to uv explicitly can otherwise override --no-config.
unset UV_CONFIG_FILE

ical_tool_venv() {
    local project_dir="$1"
    local uv_path="" python_path
    if command -v uv >/dev/null 2>&1; then
        uv_path="$(command -v uv)"
    fi

    if [[ -n "${ICAL_TOOL_PYTHON:-}" ]]; then
        python_path="$ICAL_TOOL_PYTHON"
    elif [[ -n "$uv_path" ]]; then
        python_path="$("$uv_path" python find --system --no-project \
            --no-config --no-python-downloads --no-cache </dev/null)"
    else
        python_path="$(command -v python3)"
    fi
    "$python_path" -I -B "$project_dir/_ical_tool_env.py" "$project_dir" "$uv_path"
}
