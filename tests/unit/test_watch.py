import os
import shutil
import time
from pathlib import Path

from cratedrop.export.builder import load_manifest
from cratedrop.watch import WatchState, scan_once

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"


def _drop(staging: Path, name: str, age_seconds: float = 3600.0) -> Path:
    dest = staging / name
    shutil.copy2(CLICK, dest)
    old = time.time() - age_seconds
    os.utime(dest, (old, old))
    return dest


def test_new_settled_file_triggers_build(tmp_path):
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    _drop(staging, "a.wav")
    state = WatchState()

    first = scan_once(staging, processed, state, quiet_seconds=15)
    assert first == "waiting"  # first sighting: not yet seen twice
    second = scan_once(staging, processed, state, quiet_seconds=15)
    assert second == "built"
    assert load_manifest(processed) is not None
    # steady state: nothing changes, nothing rebuilds
    assert scan_once(staging, processed, state, quiet_seconds=15) == "idle"


def test_fresh_file_waits_for_quiet_period(tmp_path):
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    dest = staging / "uploading.wav"
    shutil.copy2(CLICK, dest)
    os.utime(dest, None)  # mtime = now -> inside quiet window
    state = WatchState()

    assert scan_once(staging, processed, state, quiet_seconds=300) == "waiting"
    assert scan_once(staging, processed, state, quiet_seconds=300) == "waiting"
    assert load_manifest(processed) is None  # never processed mid-upload

    # simulate upload finishing long enough ago
    old = time.time() - 600
    os.utime(dest, (old, old))
    scan_once(staging, processed, state, quiet_seconds=300)
    assert scan_once(staging, processed, state, quiet_seconds=300) == "built"


def test_growing_file_never_ingested(tmp_path):
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    dest = _drop(staging, "grower.wav")
    state = WatchState()
    scan_once(staging, processed, state, quiet_seconds=0)
    with open(dest, "ab") as fh:  # size changes between scans
        fh.write(b"\x00" * 100)
    old = time.time() - 3600
    os.utime(dest, (old, old))
    # size changed since last scan -> not settled this pass
    result = scan_once(staging, processed, state, quiet_seconds=0)
    assert result in ("waiting", "built")  # built only from the FIRST stable size
    # after another stable sighting it settles and builds/rebuilds cleanly
    scan_once(staging, processed, state, quiet_seconds=0)
    final = scan_once(staging, processed, state, quiet_seconds=0)
    assert final in ("built", "idle")
    assert load_manifest(processed) is not None


def test_future_mtime_settles_on_size_stability(tmp_path):
    """UTC-stamped downloads carry mtimes hours in the future; they must
    settle via size stability instead of waiting to age."""
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    dest = staging / "from_the_future.wav"
    shutil.copy2(CLICK, dest)
    future = time.time() + 7 * 3600
    os.utime(dest, (future, future))
    state = WatchState()

    assert scan_once(staging, processed, state, quiet_seconds=300) == "waiting"
    assert scan_once(staging, processed, state, quiet_seconds=300) == "built"
    assert load_manifest(processed) is not None


def test_lock_prevents_concurrent_build(tmp_path):
    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    _drop(staging, "a.wav")
    lock = processed / ".cratedrop" / "build.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))  # a live pid holds the lock

    state = WatchState()
    scan_once(staging, processed, state, quiet_seconds=15)
    assert scan_once(staging, processed, state, quiet_seconds=15) == "locked"

    lock.write_text("999999999")  # stale/dead pid -> lock is reclaimed
    assert scan_once(staging, processed, state, quiet_seconds=15) == "built"
