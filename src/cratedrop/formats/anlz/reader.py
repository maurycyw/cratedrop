"""Thin wrapper over pyrekordbox's construct-based ANLZ parser."""

from __future__ import annotations

from pathlib import Path

from pyrekordbox.anlz import AnlzFile

ANLZ_SUFFIXES = {".DAT", ".EXT", ".2EX"}


def is_anlz_path(path: Path) -> bool:
    return path.suffix.upper() in ANLZ_SUFFIXES


def parse_anlz(path: Path) -> AnlzFile:
    return AnlzFile.parse_file(path)


def summarize_tags(anlz: AnlzFile) -> list[dict[str, object]]:
    """One row per tag: type, payload size, and a short human summary."""
    rows: list[dict[str, object]] = []
    for tag in anlz.tags:
        s = tag.struct
        summary = ""
        t = tag.type
        try:
            if t in ("PQTZ", "PQT2") and hasattr(tag, "get_bpms"):
                bpms = sorted(set(tag.get_bpms()))
                beats = getattr(s, "entry_count", len(getattr(s, "entries", []) or []))
                summary = f"{beats} beats, bpm {bpms[:4]}"
            elif t == "PPTH":
                summary = s.path
            elif t.startswith("PWV") or t == "PWAV":
                n = getattr(s, "len_entries", getattr(s, "entry_count", "?"))
                summary = f"{n} entries"
            elif t in ("PCOB", "PCO2"):
                kind = getattr(s, "type", "?")
                count = getattr(s, "count", getattr(s, "len_cues", "?"))
                summary = f"cue list type={kind} count={count}"
        except Exception as exc:  # noqa: BLE001 - inspect must never die on one tag
            summary = f"<summary failed: {exc}>"
        rows.append({
            "type": t,
            "bytes": getattr(s, "len_tag", 0),
            "summary": summary,
        })
    return rows
