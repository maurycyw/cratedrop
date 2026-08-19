"""`cratedrop inspect` — pretty-print device databases, ANLZ files, USB trees."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from .formats.anlz.reader import is_anlz_path, parse_anlz, summarize_tags
from .formats.pdb.vendor_api import Database, ExtDatabase


def inspect_path(console: Console, path: Path) -> None:
    path = path.expanduser()
    if not path.exists():
        console.print(f"[red]{path} does not exist[/red]")
        raise SystemExit(1)
    if path.is_dir():
        _inspect_tree(console, path)
    elif path.name.lower() == "exportext.pdb":
        _inspect_ext_pdb(console, path)
    elif path.suffix.lower() == ".pdb":
        _inspect_pdb(console, path)
    elif is_anlz_path(path):
        _inspect_anlz(console, path)
    else:
        console.print(f"[red]don't know how to inspect {path.name}[/red]")
        raise SystemExit(1)


def _inspect_tree(console: Console, root: Path) -> None:
    pdb = root / "PIONEER" / "rekordbox" / "export.pdb"
    ext = root / "PIONEER" / "rekordbox" / "exportExt.pdb"
    anlz_root = root / "PIONEER" / "USBANLZ"
    contents = root / "Contents"

    console.print(f"[bold]{root}[/bold]")
    audio_files = ([p for p in contents.rglob("*") if p.is_file()]
                   if contents.exists() else [])
    console.print(f"  Contents/: {len(audio_files)} files"
                  if contents.exists() else "  [dim]no Contents/[/dim]")
    anlz_files = ([p for p in anlz_root.rglob("ANLZ*") if p.is_file()]
                  if anlz_root.exists() else [])
    console.print(f"  USBANLZ/: {len(anlz_files)} analysis files"
                  if anlz_root.exists() else "  [dim]no USBANLZ/[/dim]")

    if pdb.exists():
        _inspect_pdb(console, pdb)
    else:
        console.print("  [dim]no export.pdb[/dim]")
    if ext.exists():
        _inspect_ext_pdb(console, ext)


def _inspect_pdb(console: Console, path: Path) -> None:
    db = Database.from_file(path)
    console.print(f"\n[bold]{path}[/bold] ({path.stat().st_size:,} bytes)")

    counts = Table(show_header=False, box=None, pad_edge=False)
    for name in ("tracks", "artists", "albums", "genres", "keys", "colors",
                 "labels", "playlist_tree", "playlist_entries", "artwork",
                 "history_playlists", "history_entries"):
        counts.add_row(name, str(len(getattr(db, name))))
    console.print(counts)

    if db.tracks:
        artists = {a.id: a.name for a in db.artists}
        keys = {k.id: k.name for k in db.keys}
        t = Table(title=f"tracks ({len(db.tracks)})")
        for col in ("id", "title", "artist", "bpm", "key", "path"):
            t.add_column(col, overflow="fold")
        for tr in db.tracks[:50]:
            t.add_row(str(tr.id), tr.title, artists.get(tr.artist_id, ""),
                      f"{tr.tempo / 100:.2f}", keys.get(tr.key_id, ""),
                      tr.file_path)
        if len(db.tracks) > 50:
            t.add_row("…", f"(+{len(db.tracks) - 50} more)", "", "", "", "")
        console.print(t)


def _inspect_ext_pdb(console: Console, path: Path) -> None:
    ext = ExtDatabase.from_file(path)
    console.print(f"\n[bold]{path}[/bold] ({path.stat().st_size:,} bytes)")
    tags = getattr(ext, "tags", [])
    console.print(f"  My Tag rows: {len(tags)}")


def _inspect_anlz(console: Console, path: Path) -> None:
    anlz = parse_anlz(path)
    console.print(f"\n[bold]{path}[/bold] ({path.stat().st_size:,} bytes)")
    t = Table(title=f"{path.suffix.upper()} tags ({anlz.num_tags})")
    t.add_column("tag")
    t.add_column("bytes", justify="right")
    t.add_column("summary", overflow="fold")
    for row in summarize_tags(anlz):
        t.add_row(str(row["type"]), f"{row['bytes']:,}", str(row["summary"]))
    console.print(t)
