"""Harvest deck-written data from a stick: cues out of ANLZ files, play
history out of the pdb — merged back into the library cache so the DJ's
on-deck work survives every re-flash.

Parsing is raw-byte and tolerant (players and old Rekordbox versions write
variants that strict parsers reject — including loop cues, type=2).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .. import cache
from ..export.builder import load_manifest
from ..formats.pdb.vendor_api import Database
from ..model import CueKind, CuePoint, CueSource, merge_cues
from ..verify.diff import _walk_anlz_sections


@dataclass
class HarvestReport:
    tracks_updated: list[str] = field(default_factory=list)
    cues_found: int = 0
    loops_skipped: int = 0
    history_playlists: int = 0
    unmatched_anlz: list[str] = field(default_factory=list)


def _slot_letter(hot_cue_num: int) -> str:
    return chr(ord("A") + hot_cue_num - 1) if hot_cue_num >= 1 else ""


def extract_ppth(raw: bytes) -> str:
    for fourcc, section in _walk_anlz_sections(raw):
        if fourcc == "PPTH" and len(section) >= 20:
            length = struct.unpack(">I", section[12:16])[0]
            return section[16:16 + length].decode("utf-16-be").rstrip("\x00")
    return ""


def extract_cues(raw: bytes) -> tuple[list[CuePoint], int]:
    """All point cues from one ANLZ file's PCOB/PCO2 sections, as DECK cues.
    Returns (cues, skipped_loop_count). PCP2 entries (labels) are preferred
    over their PCPT twins; loops are counted but not yet modeled."""
    by_key: dict[tuple[CueKind, str, int], CuePoint] = {}
    loops = 0
    for fourcc, section in _walk_anlz_sections(raw):
        if fourcc not in ("PCOB", "PCO2"):
            continue
        body = section[24 if fourcc == "PCOB" else 20:]
        off = 0
        while off + 12 <= len(body):
            sub = body[off:off + 4]
            len_tag = struct.unpack(">I", body[off + 8:off + 12])[0]
            if len_tag < 12 or off + len_tag > len(body):
                break
            entry = body[off:off + len_tag]
            off += len_tag
            if sub == b"PCPT" and len(entry) >= 40:
                cue_type, time_ms = entry[28], struct.unpack(">I", entry[32:36])[0]
                num = struct.unpack(">I", entry[12:16])[0]
                color_id = entry[40] if len(entry) > 40 else 0
                prefer = False
            elif sub == b"PCP2" and len(entry) >= 28:
                cue_type, time_ms = entry[16], struct.unpack(">I", entry[20:24])[0]
                num = struct.unpack(">I", entry[12:16])[0]
                label_len = struct.unpack(">I", entry[40:44])[0] if len(entry) >= 44 else 0
                label = (entry[44:44 + label_len].decode("utf-16-be", errors="replace")
                         .rstrip("\x00") if label_len else "")
                color_id = 0
                prefer = True
            else:
                continue
            if cue_type == 2:
                loops += 1
                continue
            kind = CueKind.HOT if num >= 1 else CueKind.MEMORY
            key = (kind, _slot_letter(num), time_ms)
            if prefer or key not in by_key:
                by_key[key] = CuePoint(
                    kind=kind, slot=_slot_letter(num), time_ms=float(time_ms),
                    label=label if prefer else "",
                    color_id=color_id if color_id else -1,
                    source=CueSource.DECK)
    return list(by_key.values()), loops


def harvest(mount: Path, processed_dir: Path) -> HarvestReport:
    """Pull deck-written cues + history from a stick into the library cache."""
    report = HarvestReport()
    image_manifest = load_manifest(processed_dir) or {}
    stick_manifest = load_manifest(mount) or {}
    # audio path (leading slash, as ANLZ PPTH writes it) -> content sha1
    path_to_sha = {f"/{rel}": meta["sha1"] for rel, meta in image_manifest.items()
                   if rel.startswith("Contents/")}

    anlz_root = mount / "PIONEER" / "USBANLZ"
    for dat in sorted(anlz_root.rglob("ANLZ0000.*")) if anlz_root.exists() else []:
        rel = str(dat.relative_to(mount))
        known = stick_manifest.get(rel)
        if known:
            import hashlib
            if hashlib.sha1(dat.read_bytes()).hexdigest() == known["sha1"]:
                continue  # exactly what we flashed; nothing deck-written here
        raw = dat.read_bytes()
        cues, loops = extract_cues(raw)
        report.loops_skipped += loops
        if not cues:
            continue
        sha = path_to_sha.get(extract_ppth(raw))
        if sha is None:
            report.unmatched_anlz.append(rel)
            continue
        analysis = cache.load_any(processed_dir, sha)
        if analysis is None:
            report.unmatched_anlz.append(rel)
            continue
        # A stick's ANLZ contains the cues WE flashed plus anything the deck
        # added or moved. Only the latter are deck data — a cue matching a
        # known cue (same kind+slot, within 1 ms) is just our own reflection.
        def _known(c: CuePoint) -> bool:
            return any(k.kind == c.kind and k.slot == c.slot
                       and abs(k.time_ms - c.time_ms) <= 1.0
                       for k in analysis.cues)

        fresh = tuple(c for c in cues if not _known(c))
        if not fresh:
            continue
        # merge_cues treats `incoming` as the replacement set, so re-include
        # the current heuristics; deck cues come last and win slot clashes
        keep_heuristic = tuple(c for c in analysis.cues
                               if c.source == CueSource.HEURISTIC)
        merged = merge_cues(analysis.cues, keep_heuristic + fresh)
        if merged != analysis.cues:
            cache.store(processed_dir, analysis.replace_cues(merged))
            report.tracks_updated.append(analysis.meta.title)
        report.cues_found += len(cues)

    # history playlists -> local archive. Legacy decks write them into
    # export.pdb; OneLibrary decks (XDJ-AZ...) write the history table of
    # exportLibrary.db (observed live on an AZ).
    sessions: dict[str, list] = {}
    pdb_path = mount / "PIONEER" / "rekordbox" / "export.pdb"
    if pdb_path.exists():
        db = Database.from_file(pdb_path)
        tracks = {t.id: t.file_path for t in db.tracks}
        names = {h.id: h.name for h in db.history_playlists}
        for entry in db.history_entries:
            sessions.setdefault("pdb:" + names.get(entry.playlist_id, "?"), []).append(
                tracks.get(entry.track_id, f"track#{entry.track_id}"))
    onelib_path = mount / "PIONEER" / "rekordbox" / "exportLibrary.db"
    if onelib_path.exists():
        sessions.update(_onelibrary_history(onelib_path))
    if sessions:
        out = processed_dir / ".cratedrop" / "history"
        out.mkdir(parents=True, exist_ok=True)
        existing = {}
        if (out / "harvested.json").exists():
            try:
                existing = json.loads((out / "harvested.json").read_text())
            except Exception:  # noqa: BLE001
                existing = {}
        existing.update(sessions)
        (out / "harvested.json").write_text(json.dumps(existing, indent=1))
        report.history_playlists = len(sessions)
    return report


def _onelibrary_history(path: Path) -> dict[str, list]:
    """history + history_content from an exportLibrary.db, keyed
    'onelib:<name>' -> [audio paths]. Reads a scratch copy so SQLite never
    touches the stick's file."""
    import shutil
    import tempfile

    from ..formats.onelibrary import connect

    sessions: dict[str, list] = {}
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "exportLibrary.db"
        shutil.copy2(path, scratch)
        for sib in ("-wal", "-shm"):
            if path.with_name(path.name + sib).exists():
                shutil.copy2(path.with_name(path.name + sib), scratch.with_name(scratch.name + sib))
        try:
            con = connect(scratch)
            rows = con.execute(
                "SELECT h.name, c.path FROM history_content hc "
                "JOIN history h ON h.history_id = hc.history_id "
                "JOIN content c ON c.content_id = hc.content_id "
                "ORDER BY hc.history_id, hc.sequenceNo").fetchall()
            con.close()
        except Exception:  # noqa: BLE001 - unreadable/foreign db: no history
            return {}
    for name, track_path in rows:
        sessions.setdefault("onelib:" + name, []).append(track_path)
    return sessions
