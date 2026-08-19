"""Snapshot a mounted Rekordbox-exported USB into tests/fixtures/golden/<case>/.

Usage: uv run python tests/fixtures/golden/snapshot.py /Volumes/NAME case-name

Copies PIONEER/ (and Contents/ for the click case) plus a sha1 manifest.
Real-audio cases go to tests/fixtures/golden-local/ (gitignored): pass
--local for those.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    local = "--local" in sys.argv
    if len(args) != 2:
        raise SystemExit(__doc__)
    volume, case = Path(args[0]), args[1]
    if not (volume / "PIONEER").exists():
        raise SystemExit(f"{volume} has no PIONEER/ folder — is this a Rekordbox export?")

    root = Path(__file__).parent if not local else (
        Path(__file__).parent.parent / "golden-local")
    dest = root / case
    if dest.exists():
        raise SystemExit(f"{dest} already exists; delete it first if re-capturing")
    dest.mkdir(parents=True)

    manifest_lines = []
    for sub in ("PIONEER", "Contents"):
        src = volume / sub
        if not src.exists():
            continue
        shutil.copytree(src, dest / sub)
        for f in sorted((dest / sub).rglob("*")):
            if f.is_file():
                sha = hashlib.sha1(f.read_bytes()).hexdigest()
                manifest_lines.append(f"{sha}  {f.relative_to(dest)}")
    (dest / "MANIFEST.sha1").write_text("\n".join(manifest_lines) + "\n")
    print(f"captured {len(manifest_lines)} files -> {dest}")


if __name__ == "__main__":
    main()
