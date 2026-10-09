"""Prepare the launcher's cached virtual environment using only the standard library."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def cache_directory():
    configured = os.environ.get("XDG_CACHE_HOME")
    if configured and Path(configured).is_absolute():
        return Path(configured)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"
    return Path.home() / ".cache"


def environment_key(project_dir, requirements):
    python = Path(sys.executable).resolve()
    metadata = python.stat()
    identity = {
        "format": 2,
        "project": str(project_dir.resolve()),
        "python": str(python),
        "version": sys.version,
        "implementation": sys.implementation.name,
        "architecture": platform.machine(),
        "python_mtime": metadata.st_mtime_ns,
        "python_size": metadata.st_size,
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
    digest.update(b"\0")
    digest.update(requirements)
    return digest.hexdigest()


def installer_environment():
    """Keep installers independent of Python paths and pip install destinations."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("PYTHON", "PIP_"))
        and name not in ("UV_CONFIG_FILE", "UV_SYSTEM_PYTHON")
    }
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PIP_CONFIG_FILE=os.devnull,
    )
    return environment


def prepare_environment(project_dir, uv=None):
    project_dir = Path(project_dir).resolve()
    requirements = (project_dir / "requirements.txt").read_bytes()
    key = environment_key(project_dir, requirements)
    cache_root = cache_directory() / "ical-tool"
    if cache_root.resolve().is_relative_to(project_dir):
        raise OSError("cache directory must be outside the source tree")
    venv_dir = cache_root / "venvs" / key
    lock_dir = cache_root / "locks"
    venv_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    python = venv_dir / "bin" / "python"
    ready = venv_dir / ".ical-tool-ready"
    setup_options = {
        "check": True,
        "stdin": subprocess.DEVNULL,
        "stdout": sys.stderr,
        "cwd": cache_root,
        "env": installer_environment(),
    }

    # The OS releases this lock if initialization fails or the process exits.
    with (lock_dir / f"{key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ready.is_file() and python.is_file() and os.access(python, os.X_OK):
            return venv_dir

        if venv_dir.exists():
            shutil.rmtree(venv_dir)

        base_python = str(Path(sys.executable).resolve())
        if uv:
            create = [
                uv, "venv", "--no-project", "--no-config", "--no-python-downloads",
                "--cache-dir", str(cache_root / "uv"),
                "--python", base_python, str(venv_dir),
            ]
        else:
            create = [base_python, "-I", "-B", "-m", "venv", str(venv_dir)]
        subprocess.run(create, **setup_options)

        # Install the exact content used for the cache key, even if the source changes.
        snapshot = venv_dir / ".ical-tool-requirements.txt"
        snapshot.write_bytes(requirements)
        if uv:
            install = [
                uv, "pip", "install", "--no-config", "--no-python-downloads",
                "--cache-dir", str(cache_root / "uv"),
                "--python", str(python), "-r", str(snapshot),
            ]
        else:
            install = [
                str(python), "-I", "-B", "-m", "pip", "--isolated",
                "--disable-pip-version-check", "install",
                "--cache-dir", str(cache_root / "pip"), "-r", str(snapshot),
            ]
        subprocess.run(install, **setup_options)
        ready.touch()
    return venv_dir


if __name__ == "__main__":
    try:
        print(prepare_environment(Path(sys.argv[1]), sys.argv[2] or None))
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"ical-tool: failed to prepare virtual environment: {error}", file=sys.stderr)
        sys.exit(1)
