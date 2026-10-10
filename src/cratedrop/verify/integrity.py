"""End-to-end integrity verification of a built image or a flashed stick:
"will a deck accept everything here?" — run it before leaving for a gig.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from ..export.builder import load_manifest
from ..formats.pdb.vendor_api import Database
from .diff import _walk_anlz_sections


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def verify_tree(root: Path, deep: bool = False,
                on_progress=lambda msg: None) -> list[str]:
    """Returns a list of problems (empty = healthy). deep=True hashes audio
    too (reads every byte; slow on USB)."""
    problems: list[str] = []

    manifest = load_manifest(root)
    if manifest is None:
        return [f"no cratedrop manifest under {root} — not a cratedrop image/stick?"]

    on_progress(f"checking {len(manifest)} manifest entries")
    for rel, meta in manifest.items():
        path = root / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
            continue
        if path.stat().st_size != meta["size"]:
            problems.append(f"size mismatch: {rel}")
            continue
        if deep or not rel.startswith("Contents/"):
            if _sha1(path) != meta["sha1"]:
                problems.append(f"content mismatch (modified?): {rel}")

    pdb_path = root / "PIONEER" / "rekordbox" / "export.pdb"
    tracks = []
    if pdb_path.exists():
        on_progress("parsing export.pdb")
        try:
            db = Database.from_file(pdb_path)
            tracks = db.tracks
            for t in tracks:
                if not (root / t.file_path.lstrip("/")).exists():
                    problems.append(f"pdb track {t.id} audio missing: {t.file_path}")
                if t.analyze_path and not (root / t.analyze_path.lstrip("/")).exists():
                    problems.append(f"pdb track {t.id} analysis missing: {t.analyze_path}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"export.pdb failed to parse: {exc}")
    else:
        problems.append("export.pdb missing")

    anlz_root = root / "PIONEER" / "USBANLZ"
    if anlz_root.exists():
        files = [p for p in anlz_root.rglob("ANLZ0000.*") if p.is_file()]
        on_progress(f"checking {len(files)} analysis files")
        for path in files:
            raw = path.read_bytes()
            rel = path.relative_to(root)
            if raw[:4] != b"PMAI":
                problems.append(f"ANLZ bad magic: {rel}")
                continue
            len_file = struct.unpack(">I", raw[8:12])[0]
            if len_file != len(raw):
                problems.append(f"ANLZ truncated: {rel} (header says {len_file}, file is {len(raw)})")
                continue
            sections = _walk_anlz_sections(raw)
            if any(name == "<garbage>" for name, _ in sections):
                problems.append(f"ANLZ malformed section chain: {rel}")

    onelib = root / "PIONEER" / "rekordbox" / "exportLibrary.db"
    if onelib.exists():
        on_progress("checking OneLibrary database")
        try:
            from ..formats.onelibrary import connect

            con = connect(onelib)
            n = con.execute("SELECT COUNT(*) FROM content").fetchone()[0]
            for (cpath,) in con.execute("SELECT path FROM content"):
                if not (root / cpath.lstrip("/")).exists():
                    problems.append(f"OneLibrary audio missing: {cpath}")
            con.close()
            if tracks and n != len(tracks):
                problems.append(f"track count mismatch: pdb={len(tracks)} OneLibrary={n}")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"exportLibrary.db failed to open: {exc}")
    else:
        problems.append("exportLibrary.db missing (OneLibrary decks will see nothing)")

    return problems
