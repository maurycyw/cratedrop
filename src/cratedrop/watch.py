"""Watch the staging dir and rebuild the image when new audio settles.

Polling (not FSEvents/inotify) by design: filesystem events don't propagate
over SMB/NFS, and the staging dir moves to a NAS in Stage 2. A file is
ingested only once it has SETTLED — same size across consecutive scans and
untouched for a quiet period — so partially-uploaded drops (from a friend's
laptop over the network) are never processed mid-transfer.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .audio.decode import is_audio_file
from .export.builder import build_image, load_manifest


@dataclass
class WatchState:
    # path -> (size, mtime) from the previous scan
    last_scan: dict[Path, tuple[int, float]] = field(default_factory=dict)
    # settled snapshot that the current image was built from
    built: dict[Path, tuple[int, float]] = field(default_factory=dict)


def _scan(staging_dir: Path) -> dict[Path, tuple[int, float]]:
    out: dict[Path, tuple[int, float]] = {}
    for p in staging_dir.rglob("*"):
        if p.is_file() and is_audio_file(p) and not p.name.startswith("."):
            try:
                st = p.stat()
            except OSError:
                continue
            out[p] = (st.st_size, st.st_mtime)
    return out


def _acquire_lock(processed_dir: Path) -> Path | None:
    lock = processed_dir / ".cratedrop" / "build.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            os.kill(pid, 0)  # raises if not running
            return None  # another live build owns the lock
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale lock
    lock.write_text(str(os.getpid()))
    return lock


def scan_once(staging_dir: Path, processed_dir: Path, state: WatchState,
              quiet_seconds: float = 15.0, now: float | None = None,
              on_event=lambda msg: None) -> str:
    """One watcher pass. Returns the action taken:
    'built' | 'waiting' | 'idle' | 'locked'."""
    now = time.time() if now is None else now
    current = _scan(staging_dir)

    settled: dict[Path, tuple[int, float]] = {}
    unsettled = 0
    for path, (size, mtime) in current.items():
        prev = state.last_scan.get(path)
        # A future mtime (UTC-stamped downloads, other machines' clocks) would
        # never age past the quiet window — size stability across scans is the
        # settle signal in that case.
        quiet_ok = (now - mtime >= quiet_seconds) or (mtime > now)
        if size > 0 and prev == (size, mtime) and quiet_ok:
            settled[path] = (size, mtime)
        else:
            unsettled += 1
    state.last_scan = current

    if settled == state.built:
        return "waiting" if unsettled else "idle"
    added_or_changed = {p for p, sig in settled.items()
                        if state.built.get(p) != sig}
    if unsettled and not added_or_changed:
        # only removals so far, with uploads in flight — a file being
        # replaced mid-transfer looks exactly like this; wait for quiet
        return "waiting"
    if unsettled:
        on_event(f"{unsettled} file(s) still settling; will process once quiet")

    lock = _acquire_lock(processed_dir)
    if lock is None:
        return "locked"
    try:
        new = len(set(settled) - set(state.built))
        gone = len(set(state.built) - set(settled))
        on_event(f"processing: {new} new/changed, {gone} removed…")
        report = build_image(staging_dir, processed_dir)
        state.built = settled
        on_event(f"image updated: {report.tracks} tracks "
                 f"(analyzed {len(report.analyzed)}, cached {len(report.cached)})")
    finally:
        lock.unlink(missing_ok=True)
    return "built"


def watch(staging_dir: Path, processed_dir: Path, interval: float = 10.0,
          quiet_seconds: float = 15.0, on_event=lambda msg: None) -> None:
    """Run forever (Ctrl-C to stop)."""
    state = WatchState()
    # Baseline scan primes settle-detection, but built stays empty: the first
    # pass always runs one build (cheap — cache hits) so changes made while
    # the watcher was offline are caught.
    state.last_scan = _scan(staging_dir)
    has_image = load_manifest(processed_dir) is not None
    on_event(f"watching {staging_dir} ({len(state.last_scan)} tracks, "
             f"poll {interval:.0f}s, settle {quiet_seconds:.0f}s"
             + (", building initial image" if not has_image else "") + ")")
    while True:
        try:
            scan_once(staging_dir, processed_dir, state,
                      quiet_seconds=quiet_seconds, on_event=on_event)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad build must not kill the watcher
            on_event(f"error (watcher continues): {type(exc).__name__}: {exc}")
        time.sleep(interval)
