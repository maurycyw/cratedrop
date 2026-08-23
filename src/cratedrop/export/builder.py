"""Build/update the processed USB image from staged audio files.

The image is the exact tree a stick should carry:
  Contents/<Artist>/<Album>/<Track>.<ext>
  PIONEER/rekordbox/export.pdb  (+ exportExt.pdb)
  PIONEER/USBANLZ/P.../..../ANLZ0000.{DAT,EXT,2EX}
  PIONEER/.cratedrop.json       (manifest: everything we authored, with sha1s)

Audio copies and analysis are incremental (sha1-keyed cache); the pdb and
ANLZ files are cheap and rebuilt from the template on every run.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .. import cache
from ..analysis.waveform import SAMPLE_RATE, analyze_waveform
from ..audio.decode import decode_mono, is_audio_file
from ..audio.tags import read_meta, tag_bpm
from ..formats.anlz import writer as anlz_writer
from ..formats.onelibrary import OneLibTrack, write_onelibrary
from ..formats.pdb.builder import PdbBuilder
from ..model import BeatGrid, TrackAnalysis
from .layout import dedupe, usb_audio_path

MANIFEST_REL = "PIONEER/.cratedrop.json"
INGEST_DATES_REL = ".cratedrop/ingest-dates.json"


def _load_ingest_dates(processed_dir: Path) -> dict[str, str]:
    path = processed_dir / INGEST_DATES_REL
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _ingest_date(dates: dict[str, str], sha: str, first_run: bool) -> str:
    """ISO date a track was first ingested; stable once recorded. Tracks that
    existed before this feature (the store's very first run) get "" — no
    retroactive date playlists, only tracks added from now on."""
    if sha in dates:
        return dates[sha]
    import datetime
    dates[sha] = "" if first_run else datetime.date.today().isoformat()
    return dates[sha]


def _fallback_date(src: Path) -> str:
    """dateAdded for pre-feature tracks (no ingest stamp): file mtime."""
    import datetime
    return datetime.date.fromtimestamp(src.stat().st_mtime).isoformat()


def _playlist_name(iso_date: str) -> str:
    y, m, d = iso_date.split("-")
    return f"{m}/{d}/{y}"

# Default seed: a genuine zero-track export authored by Rekordbox 7.2.18
# (golden 'empty' capture) — keeps every undocumented header field bit-true.
_TEMPLATES = files("cratedrop.formats.pdb") / "templates"


@dataclass
class BuildReport:
    analyzed: list[str]
    cached: list[str]
    copied: list[str]
    tracks: int
    warnings: list[str]


def scan_staging(staging_dir: Path) -> list[Path]:
    """Newest first (file mtime): with a massive library, an interrupted
    process/sync has still covered the most recent tracks."""
    files = [p for p in staging_dir.rglob("*")
             if p.is_file() and is_audio_file(p) and not p.name.startswith(".")]
    return sorted(files, key=lambda p: (-p.stat().st_mtime, p.name))


def analyze_track(path: Path, processed_dir: Path,
                  staging_dir: Path | None = None) -> tuple[TrackAnalysis, bool]:
    """Returns (analysis, was_cached). Each DSP stage degrades gracefully:
    beat tracker failure falls back to tag BPM (or 128) with a warning-level
    confidence of 0, key/cue failures just omit that data."""
    meta = read_meta(path, base_dir=staging_dir)
    if not meta.artist:
        # enrichment fills blanks only — tags/folders/manual always win
        from dataclasses import replace as _replace

        from .. import enrich
        enr = enrich.load(processed_dir, meta.sha1)
        if enr and enr.get("artist"):
            meta = _replace(meta, artist=enr["artist"],
                            album=meta.album or enr.get("album", ""))
    cached = cache.load(processed_dir, meta.sha1)
    if cached is not None:
        if cached.meta != meta:
            # metadata rules changed or tags were edited — refresh without
            # discarding the (expensive) DSP results
            from dataclasses import replace
            cached = replace(cached, meta=meta)
            cache.store(processed_dir, cached)
        return cached, True

    samples = decode_mono(path, SAMPLE_RATE)
    waveform = analyze_waveform(samples)
    duration_ms = meta.duration_ms or len(samples) / SAMPLE_RATE * 1000.0

    from ..analysis.beats import detect_grid
    from ..analysis.cues import place_cues
    from ..analysis.key import detect_key

    try:
        grid = detect_grid(samples, SAMPLE_RATE, duration_ms)
    except Exception:  # noqa: BLE001 - tracker failure must not block export
        bpm = tag_bpm(path) or 128.0
        grid = BeatGrid.constant(bpm=bpm, first_beat_ms=0.0,
                                 duration_ms=duration_ms, confidence=0.0)
    key = detect_key(samples, SAMPLE_RATE, source_path=path)
    try:
        cues = place_cues(grid, waveform)
    except Exception:  # noqa: BLE001
        cues = ()

    # Re-analysis must never lose user data: carry deck/manual cues from any
    # prior cache entry (even a stale-version one) over the fresh heuristics.
    from ..model import CueSource, merge_cues
    stale = cache.load_any(processed_dir, meta.sha1)
    if stale is not None:
        user_cues = tuple(c for c in stale.cues if c.source != CueSource.HEURISTIC)
        if user_cues:
            cues = merge_cues(user_cues, cues)

    analysis = TrackAnalysis(meta=meta, grid=grid, key=key, cues=cues,
                             waveform=waveform,
                             analyzer_versions=dict(cache.ANALYZER_VERSIONS))
    from .. import overrides
    analysis = overrides.apply(analysis, overrides.load(processed_dir, meta.sha1))
    cache.store(processed_dir, analysis)
    return analysis, False


def _template_paths(golden_dir: Path | None) -> tuple[Path, Path]:
    """(export template, exportExt template)."""
    if golden_dir:
        pdb = golden_dir / "PIONEER" / "rekordbox" / "export.pdb"
        ext = golden_dir / "PIONEER" / "rekordbox" / "exportExt.pdb"
        if pdb.exists():
            return pdb, ext
    return (Path(str(_TEMPLATES / "empty-export.pdb")),
            Path(str(_TEMPLATES / "empty-exportExt.pdb")))


def build_image(staging_dir: Path, processed_dir: Path,
                template_dir: Path | None = None, on_track=None) -> BuildReport:
    """on_track(index, total, name) is called before each track processes."""
    report = BuildReport(analyzed=[], cached=[], copied=[], tracks=0, warnings=[])
    processed_dir.mkdir(parents=True, exist_ok=True)

    template_pdb, template_ext = _template_paths(template_dir)
    builder = PdbBuilder.from_template(template_pdb)
    taken = {t.file_path.lower() for t in builder.db.tracks}
    manifest: dict[str, dict] = {}
    art_ids: dict[str, int] = {}  # image sha1 -> artwork row id
    art_b_rel: dict[str, str] = {}  # image sha1 -> OneLibrary image path
    track_art_sha: dict[str, str] = {}  # track sha1 -> image sha1

    def track_artwork(src: Path, track_sha: str) -> int:
        from .. import enrich
        from ..audio.artwork import extract_embedded_art, render_pioneer_jpegs

        raw = extract_embedded_art(src)
        if raw is None:
            # enrichment fallback: web-fetched art cached by cratedrop enrich
            enr_art = enrich.art_path(processed_dir, track_sha)
            raw = enr_art.read_bytes() if enr_art.exists() else None
        if raw is None:
            return 0
        sha = hashlib.sha1(raw).hexdigest()
        track_art_sha[track_sha] = sha
        if sha in art_ids:
            return art_ids[sha]
        rendered = render_pioneer_jpegs(raw)
        if rendered is None:
            return 0
        small, medium = rendered
        n = len(art_ids) + 1
        art_rel = f"PIONEER/Artwork/00001/a{n}.jpg"
        # OneLibrary references the same art under a 'b' prefix
        art_b_rel[sha] = f"/PIONEER/Artwork/00001/b{n}.jpg"
        for rel, data in ((art_rel, small),
                          (f"PIONEER/Artwork/00001/a{n}_m.jpg", medium),
                          (f"PIONEER/Artwork/00001/b{n}.jpg", small),
                          (f"PIONEER/Artwork/00001/b{n}_m.jpg", medium)):
            dest = processed_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            manifest[rel] = {"size": len(data),
                             "sha1": hashlib.sha1(data).hexdigest()}
        art_ids[sha] = builder.get_or_create_artwork("/" + art_rel)
        return art_ids[sha]

    playlist_id = builder.create_playlist("cratedrop")
    ingest_dates = _load_ingest_dates(processed_dir)
    first_ingest_run = not ingest_dates
    by_date: dict[str, list[int]] = {}
    onelib_tracks: list[OneLibTrack] = []
    onelib_index: dict[int, int] = {}  # pdb track id -> onelib_tracks index

    def checkpoint() -> None:
        """Persist a valid image right now: an interrupted run over a huge
        library still leaves the newest tracks flashable."""
        pdb_dir = processed_dir / "PIONEER" / "rekordbox"
        pdb_dir.mkdir(parents=True, exist_ok=True)
        builder.save(pdb_dir / "export.pdb")
        if template_ext.exists() and not (pdb_dir / "exportExt.pdb").exists():
            shutil.copy2(template_ext, pdb_dir / "exportExt.pdb")
        snapshot = dict(manifest)
        for name in ("export.pdb", "exportExt.pdb"):
            path = pdb_dir / name
            if path.exists():
                snapshot[f"PIONEER/rekordbox/{name}"] = {
                    "size": path.stat().st_size,
                    "sha1": hashlib.sha1(path.read_bytes()).hexdigest()}
        (processed_dir / MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
        (processed_dir / MANIFEST_REL).write_text(
            json.dumps(snapshot, indent=1, sort_keys=True))

    staged = scan_staging(staging_dir)
    for i, src in enumerate(staged):
        if on_track is not None:
            on_track(i, len(staged), src.name)
        analysis, was_cached = analyze_track(src, processed_dir, staging_dir)
        (report.cached if was_cached else report.analyzed).append(src.name)

        rel_audio = dedupe(usb_audio_path(analysis.meta), taken)
        taken.add(rel_audio.lower())

        dest = processed_dir / rel_audio.lstrip("/")
        if not dest.exists() or dest.stat().st_size != analysis.meta.file_size:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            report.copied.append(rel_audio)
        manifest[rel_audio.lstrip("/")] = {"size": dest.stat().st_size,
                                           "sha1": analysis.meta.sha1}

        written = anlz_writer.write_anlz(analysis, rel_audio, processed_dir)
        anlz_dat_rel = "/" + str(written["ANLZ0000.DAT"].relative_to(processed_dir))
        for path in written.values():
            rel = str(path.relative_to(processed_dir))
            manifest[rel] = {"size": path.stat().st_size,
                             "sha1": hashlib.sha1(path.read_bytes()).hexdigest()}

        track_id = builder.add_track(analysis, rel_audio, anlz_dat_rel,
                                     artwork_id=track_artwork(src, analysis.meta.sha1))
        builder.add_to_playlist(playlist_id, track_id)
        date = _ingest_date(ingest_dates, analysis.meta.sha1, first_ingest_run)
        if date:
            by_date.setdefault(date, []).append(track_id)
        onelib_tracks.append(OneLibTrack(
            analysis=analysis, usb_path=rel_audio, anlz_dat_path=anlz_dat_rel,
            image_path=art_b_rel.get(track_art_sha.get(analysis.meta.sha1, ""), None),
            date_added=date or _fallback_date(src)))
        onelib_index[track_id] = len(onelib_tracks) - 1
        report.tracks += 1
        if not was_cached and report.tracks % 25 == 0:
            checkpoint()

    # date-added playlists, newest first (MM/DD/YYYY, one per ingest day)
    for date in sorted(by_date, reverse=True):
        pid = builder.create_playlist(_playlist_name(date))
        for track_id in by_date[date]:
            builder.add_to_playlist(pid, track_id)
    dates_path = processed_dir / INGEST_DATES_REL
    dates_path.parent.mkdir(parents=True, exist_ok=True)
    dates_path.write_text(json.dumps(ingest_dates, indent=1, sort_keys=True))

    pdb_dir = processed_dir / "PIONEER" / "rekordbox"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    builder.save(pdb_dir / "export.pdb")
    if template_ext.exists():
        shutil.copy2(template_ext, pdb_dir / "exportExt.pdb")
    # OneLibrary (XDJ-AZ / Opus Quad / CDJ-3000X): same tracks, same playlists
    onelib_playlists = [("cratedrop", [onelib_index[t] for t in onelib_index])]
    for date in sorted(by_date, reverse=True):
        onelib_playlists.append((_playlist_name(date),
                                 [onelib_index[t] for t in by_date[date]]))
    written = write_onelibrary(pdb_dir, onelib_tracks, onelib_playlists)
    for name in ["export.pdb", "exportExt.pdb"] + [p.name for p in written]:
        path = pdb_dir / name
        if path.exists():
            rel = f"PIONEER/rekordbox/{name}"
            manifest[rel] = {"size": path.stat().st_size,
                             "sha1": hashlib.sha1(path.read_bytes()).hexdigest()}

    manifest_path = processed_dir / MANIFEST_REL
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))

    # GC: the processed dir is fully machine-managed, so any Contents/USBANLZ
    # file not in the fresh manifest is an orphan from renamed paths (e.g.
    # after a metadata fix changed the layout) — delete it and empty dirs.
    # Compare case-insensitively: the filesystem folds case (macOS, FAT), so
    # "Contents/CADZOW/x.wav" on disk may satisfy a "Contents/Cadzow/x.wav"
    # manifest entry.
    manifest_fold = {k.lower() for k in manifest}
    for sub in ("Contents", "PIONEER/USBANLZ", "PIONEER/Artwork"):
        root = processed_dir / sub
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if f.is_file() and str(f.relative_to(processed_dir)).lower() not in manifest_fold:
                f.unlink()
        for d in sorted((p for p in root.rglob("*") if p.is_dir()),
                        key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
    return report


def load_manifest(root: Path) -> dict[str, dict] | None:
    path = root / MANIFEST_REL
    if not path.exists():
        return None
    return json.loads(path.read_text())
