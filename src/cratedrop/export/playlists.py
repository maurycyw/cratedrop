"""Playlist assembly for the USB image.

Sources, all additive:
  * the all-tracks "cratedrop" playlist (always)
  * ingest-date playlists MM/DD/YYYY (config: playlists-by-date, default on)
  * top-level staging folders (config: playlists-from-folders, default off —
    Artist/Album-organized libraries would turn into noise)
  * any .m3u/.m3u8 file inside the staging dir (always: dropping one is
    explicit intent). Entries resolve by absolute path, path relative to the
    playlist file, or filename — M3Us exported elsewhere reference paths
    that don't exist here, so the filename match is the workhorse.
"""

from __future__ import annotations

from pathlib import Path


def resolve_m3u(m3u: Path, by_path: dict[str, int],
                by_name: dict[str, int]) -> list[int]:
    """Track ids for one playlist file. by_path: resolved source path ->
    track id; by_name: lowercase filename -> track id."""
    ids: list[int] = []
    try:
        lines = m3u.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ids
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        entry = entry.replace("\\", "/")
        candidates = []
        p = Path(entry)
        if p.is_absolute():
            candidates.append(p)
        candidates.append(m3u.parent / entry)
        tid = None
        for cand in candidates:
            try:
                tid = by_path.get(str(cand.resolve()))
            except OSError:
                tid = None
            if tid is not None:
                break
        if tid is None:
            tid = by_name.get(Path(entry).name.lower())
        if tid is not None and tid not in ids:
            ids.append(tid)
    return ids


def folder_playlists(staging_dir: Path,
                     src_to_id: dict[Path, int]) -> list[tuple[str, list[int]]]:
    """One playlist per top-level staging folder (sorted, non-empty only)."""
    groups: dict[str, list[int]] = {}
    for src, tid in src_to_id.items():
        try:
            rel = src.resolve().relative_to(staging_dir.resolve())
        except ValueError:
            continue
        if len(rel.parts) < 2:
            continue  # loose files at the root belong to no folder playlist
        groups.setdefault(rel.parts[0], []).append(tid)
    return sorted(groups.items())


def m3u_playlists(staging_dir: Path,
                  src_to_id: dict[Path, int]) -> list[tuple[str, list[int]]]:
    by_path = {str(p.resolve()): tid for p, tid in src_to_id.items()}
    by_name = {p.name.lower(): tid for p, tid in src_to_id.items()}
    out = []
    for m3u in sorted(staging_dir.rglob("*.m3u*")):
        if m3u.suffix.lower() not in (".m3u", ".m3u8"):
            continue
        ids = resolve_m3u(m3u, by_path, by_name)
        if ids:
            out.append((m3u.stem, ids))
    return out
