"""Import a Rekordbox library export (rekordbox.xml): cues, loops, grids,
playlists — so switching to cratedrop loses none of a DJ's accumulated work.

Rekordbox: File > Export Collection in xml format. Tracks are matched to the
staging library by path, then by filename. Imported cues/loops are MANUAL
user data (they always win over heuristics and survive re-analysis — for
tracks not yet analyzed they're stored as a stale cache stub that the next
analysis run folds in). Playlists become .m3u8 files in the staging dir,
feeding the normal playlist machinery. Grids import as per-track overrides
with --with-grids (single-tempo grids only; cratedrop's own segmented
detection usually beats a stale XML grid on edits).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import cache, overrides
from .audio.tags import sha1_file
from .export.builder import scan_staging
from .model import (
    CueKind,
    CuePoint,
    CueSource,
    TrackAnalysis,
    TrackMeta,
    merge_cues,
)

PLAYLIST_DIR_NAME = "rekordbox playlists"


@dataclass
class ImportReport:
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    cues: int = 0
    loops: int = 0
    grids: int = 0
    playlists: list[str] = field(default_factory=list)
    multi_tempo_skipped: int = 0


def _marks_to_cues(track) -> tuple[list[CuePoint], int]:
    cues: list[CuePoint] = []
    loops = 0
    for m in track.marks:
        num = int(m["Num"])
        is_loop = (m["Type"] == "loop") and m["End"] is not None
        if is_loop:
            loops += 1
        if num >= 8:  # beyond hot cue H
            continue
        cues.append(CuePoint(
            kind=CueKind.MEMORY if num < 0 else CueKind.HOT,
            slot="" if num < 0 else chr(ord("A") + num),
            time_ms=float(m["Start"]) * 1000.0,
            label=m["Name"] or "",
            source=CueSource.MANUAL,
            loop_out_ms=float(m["End"]) * 1000.0 if is_loop else None))
    return cues, loops


def _store_cues(processed_dir: Path, src: Path, sha: str,
                cues: list[CuePoint]) -> None:
    existing = cache.load_any(processed_dir, sha)
    if existing is None:
        # not analyzed yet: a version-less stub; the next analysis run
        # replaces everything except the user cues it must preserve
        stub = TrackAnalysis(meta=TrackMeta(source_path=str(src),
                                            title=src.stem, sha1=sha),
                             cues=tuple(cues))
        cache.store(processed_dir, stub)
        return
    keep_heuristic = tuple(c for c in existing.cues
                           if c.source == CueSource.HEURISTIC)
    merged = merge_cues(existing.cues, keep_heuristic + tuple(cues))
    if merged != existing.cues:
        cache.store(processed_dir, existing.replace_cues(merged))


def _walk_playlists(node, prefix: str = ""):
    for child in node.get_playlists():
        name = f"{prefix}{child.name}"
        if child.is_folder:
            yield from _walk_playlists(child, prefix=f"{name} - ")
        else:
            yield name, child


def import_xml(xml_path: Path, staging_dir: Path, processed_dir: Path,
               with_grids: bool = False,
               on_progress=lambda msg: None) -> ImportReport:
    from pyrekordbox.rbxml import RekordboxXml

    xml = RekordboxXml(xml_path)
    report = ImportReport()

    staged = scan_staging(staging_dir)
    by_path = {str(p.resolve()): p for p in staged}
    by_name = {p.name.lower(): p for p in staged}

    on_progress(f"matching {len(xml.get_tracks())} XML tracks against "
                f"{len(staged)} staged files")
    matched_src: dict[str, Path] = {}  # XML TrackID -> staged file
    for t in xml.get_tracks():
        loc = t["Location"] or ""
        src = by_path.get(str(Path(loc).resolve())) if loc else None
        if src is None and loc:
            src = by_name.get(Path(loc).name.lower())
        if src is None:
            report.unmatched.append(Path(loc).name if loc else "<no location>")
            continue
        report.matched += 1
        matched_src[str(t["TrackID"])] = src

        cues, loops = _marks_to_cues(t)
        sha = sha1_file(src)
        if cues:
            _store_cues(processed_dir, src, sha, cues)
            report.cues += len(cues)
            report.loops += loops

        if with_grids and t.tempos:
            if len(t.tempos) == 1:
                tempo = t.tempos[0]
                overrides.store(processed_dir, sha,
                                bpm=float(tempo["Bpm"]),
                                first_beat_ms=float(tempo["Inizio"]) * 1000.0)
                report.grids += 1
            else:
                report.multi_tempo_skipped += 1

    root = xml.get_playlist()
    out_dir = staging_dir / PLAYLIST_DIR_NAME
    for name, node in _walk_playlists(root):
        names = [matched_src[str(k)].name for k in node.get_tracks()
                 if str(k) in matched_src]
        if not names:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c not in '/\\:' else "_" for c in name).strip() or "playlist"
        (out_dir / f"{safe}.m3u8").write_text(
            "#EXTM3U\n" + "\n".join(names) + "\n", encoding="utf-8")
        report.playlists.append(safe)
    return report
