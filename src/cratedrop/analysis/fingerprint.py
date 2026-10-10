"""Acoustic fingerprinting (chromaprint/fpcalc) for near-duplicate detection.

Two files are near-duplicates when they are the same recording in different
containers/encodings/rips — invisible to sha1, obvious to a fingerprint.
Similarity = 1 - best bit-error-rate between the raw chromaprint integer
streams over small alignment offsets (different rips often disagree on
leading silence).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

FP_SECONDS = 120
OFFSET_SEARCH = 24  # chromaprint frames (~8 frames/sec)


def available() -> bool:
    return shutil.which("fpcalc") is not None


def fingerprint(path: Path) -> list[int] | None:
    if not available():
        return None
    out = subprocess.run(
        ["fpcalc", "-raw", "-json", "-length", str(FP_SECONDS), str(path)],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)["fingerprint"]
    except Exception:  # noqa: BLE001
        return None


def cached_fingerprint(path: Path, sha1: str, processed_dir: Path) -> list[int] | None:
    cache = processed_dir / ".cratedrop" / "fingerprints" / f"{sha1}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text())
        except Exception:  # noqa: BLE001
            pass
    fp = fingerprint(path)
    if fp is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(fp))
    return fp


def similarity(a: list[int], b: list[int]) -> float:
    """1.0 = identical audio; ~0.5 = unrelated (random bits)."""
    if not a or not b:
        return 0.0
    best_ber = 1.0
    for offset in range(-OFFSET_SEARCH, OFFSET_SEARCH + 1):
        if offset >= 0:
            xs, ys = a[offset:], b
        else:
            xs, ys = a, b[-offset:]
        n = min(len(xs), len(ys))
        if n < 32:
            continue
        errors = sum(((xs[i] ^ ys[i]) & 0xFFFFFFFF).bit_count() for i in range(n))
        best_ber = min(best_ber, errors / (32.0 * n))
    return 1.0 - best_ber


def find_duplicates(entries: list[tuple[Path, str]], processed_dir: Path,
                    threshold: float = 0.80,
                    on_progress=lambda i, n: None) -> list[list[tuple[Path, float]]]:
    """entries: (source path, sha1). Returns groups of (path, similarity to
    the group seed); each group has >= 2 members."""
    fps = []
    for i, (path, sha) in enumerate(entries):
        on_progress(i, len(entries))
        fp = cached_fingerprint(path, sha, processed_dir)
        if fp:
            fps.append((path, fp))
    groups: list[list[tuple[Path, float]]] = []
    used: set[int] = set()
    for i in range(len(fps)):
        if i in used:
            continue
        group = [(fps[i][0], 1.0)]
        for j in range(i + 1, len(fps)):
            if j in used:
                continue
            score = similarity(fps[i][1], fps[j][1])
            if score >= threshold:
                group.append((fps[j][0], score))
                used.add(j)
        if len(group) > 1:
            used.add(i)
            groups.append(group)
    return groups
