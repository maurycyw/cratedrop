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
from ..formats.pdb.builder import PdbBuilder
from ..model import BeatGrid, TrackAnalysis
from .layout import dedupe, usb_audio_path

MANIFEST_REL = "PIONEER/.cratedrop.json"

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
                template_dir: Path | None = None) -> BuildReport:
    report = BuildReport(analyzed=[], cached=[], copied=[], tracks=0, warnings=[])
    processed_dir.mkdir(parents=True, exist_ok=True)

    template_pdb, template_ext = _template_paths(template_dir)
    builder = PdbBuilder.from_template(template_pdb)
    taken = {t.file_path.lower() for t in builder.db.tracks}
    manifest: dict[str, dict] = {}
    art_ids: dict[str, int] = {}  # image sha1 -> artwork row id

    def track_artwork(src: Path) -> int:
        from ..audio.artwork import extract_embedded_art, render_pioneer_jpegs

        raw = extract_embedded_art(src)
        if raw is None:
            return 0
        sha = hashlib.sha1(raw).hexdigest()
        if sha in art_ids:
            return art_ids[sha]
        rendered = render_pioneer_jpegs(raw)
        if rendered is None:
            return 0
        small, medium = rendered
        n = len(art_ids) + 1
        art_rel = f"PIONEER/Artwork/00001/a{n}.jpg"
        for rel, data in ((art_rel, small),
                          (f"PIONEER/Artwork/00001/a{n}_m.jpg", medium)):
            dest = processed_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            manifest[rel] = {"size": len(data),
                             "sha1": hashlib.sha1(data).hexdigest()}
        art_ids[sha] = builder.get_or_create_artwork("/" + art_rel)
        return art_ids[sha]

    playlist_id = builder.create_playlist("cratedrop")

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

    for src in scan_staging(staging_dir):
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
                                     artwork_id=track_artwork(src))
        builder.add_to_playlist(playlist_id, track_id)
        report.tracks += 1
        if not was_cached and report.tracks % 25 == 0:
            checkpoint()

    pdb_dir = processed_dir / "PIONEER" / "rekordbox"
    pdb_dir.mkdir(parents=True, exist_ok=True)
    builder.save(pdb_dir / "export.pdb")
    if template_ext.exists():
        shutil.copy2(template_ext, pdb_dir / "exportExt.pdb")
    for name in ("export.pdb", "exportExt.pdb"):
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
