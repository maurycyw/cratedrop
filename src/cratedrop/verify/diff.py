"""Structure-aware diffs for pdb and ANLZ files (and whole USB trees).

The point is localization: "PWV5 payload differs at bin 3021" or "tracks page
54, rows changed", never just "files differ". Byte-level noise that two
equivalent exports legitimately disagree on (save counters, generation stamps)
is masked by default; --raw shows it.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path

from rich.console import Console

from ..formats.anlz.reader import is_anlz_path
from ..formats.pdb.vendor_api import Database, TableType

# Byte ranges that legitimately differ between semantically equal files.
# File header (page 0): 0x14 u32 save-sequence number.
_HEADER_MASK = [(0x14, 0x18)]
# Every page header: 0x10 u32 generation stamp, 0x20 u16 rows-written-this-
# save, 0x22 u16 slot-count-at-previous-write (see rekordbox-pdb FORMAT.md).
_PAGE_MASK = [(0x10, 0x14), (0x20, 0x24)]

_SEMANTIC_TABLES = (
    "tracks", "artists", "albums", "genres", "keys", "colors", "labels",
    "playlist_tree", "playlist_entries", "artwork",
    "history_playlists", "history_entries",
)


def diff_paths(console: Console, ours: Path, golden: Path,
               show_masked: bool = False) -> bool:
    """Returns True if a (non-masked) difference was found."""
    ours, golden = ours.expanduser(), golden.expanduser()
    if ours.is_dir() and golden.is_dir():
        return _diff_trees(console, ours, golden, show_masked)
    if ours.suffix.lower() == ".pdb":
        return diff_pdb(console, ours, golden, show_masked)
    if is_anlz_path(ours):
        return diff_anlz(console, ours, golden)
    a, b = ours.read_bytes(), golden.read_bytes()
    if a == b:
        console.print(f"[green]identical[/green] {ours.name}")
        return False
    console.print(f"[red]binary differs[/red] {ours.name}: "
                  f"{len(a):,} vs {len(b):,} bytes")
    return True


def _diff_trees(console: Console, ours: Path, golden: Path,
                show_masked: bool) -> bool:
    ours_files = {p.relative_to(ours) for p in ours.rglob("*") if p.is_file()}
    golden_files = {p.relative_to(golden) for p in golden.rglob("*") if p.is_file()}
    changed = False
    for rel in sorted(golden_files - ours_files):
        console.print(f"[red]missing from ours:[/red] {rel}")
        changed = True
    for rel in sorted(ours_files - golden_files):
        console.print(f"[yellow]extra in ours:[/yellow] {rel}")
        changed = True
    for rel in sorted(ours_files & golden_files):
        a, b = ours / rel, golden / rel
        if a.read_bytes() == b.read_bytes():
            continue
        console.print(f"\n[bold]--- {rel} ---[/bold]")
        changed |= diff_paths(console, a, b, show_masked)
    if not changed:
        console.print("[green]trees match[/green]")
    return changed


# -- pdb ---------------------------------------------------------------------


def _table_name(table_type: int) -> str:
    try:
        return TableType(table_type).name.lower()
    except ValueError:
        return f"table_{table_type}"


def _page_owner_map(db: Database) -> dict[int, str]:
    """page index -> owning table name, by walking each table's page chain."""
    raw = db._data
    owners: dict[int, str] = {0: "file_header"}
    for table in db.tables:
        name = _table_name(table.type)
        page_index = table.first_page
        seen = set()
        while page_index not in seen:
            seen.add(page_index)
            owners.setdefault(page_index, name)
            if page_index == table.last_page:
                break
            start = page_index * db.page_size
            page = raw[start:start + db.page_size]
            if len(page) < 16:
                break
            page_index = int.from_bytes(page[12:16], "little")
    return owners


def _row_key(row) -> tuple:
    """Identity key for matching rows across files (id when present)."""
    if hasattr(row, "id"):
        return (type(row).__name__, row.id)
    return (type(row).__name__, repr(row))


def _row_fields(row) -> dict:
    if is_dataclass(row):
        return {f.name: getattr(row, f.name) for f in fields(row)}
    return {"repr": repr(row)}


def diff_pdb(console: Console, ours_path: Path, golden_path: Path,
             show_masked: bool = False) -> bool:
    ours = Database.from_file(ours_path)
    golden = Database.from_file(golden_path)
    changed = False

    # 1. semantic tier: table-by-table row comparison
    for table in _SEMANTIC_TABLES:
        a_rows = {_row_key(r): r for r in getattr(ours, table)}
        b_rows = {_row_key(r): r for r in getattr(golden, table)}
        added = sorted(set(a_rows) - set(b_rows))
        removed = sorted(set(b_rows) - set(a_rows))
        for key in added:
            console.print(f"[yellow]{table}: only in ours[/yellow] {a_rows[key]}")
        for key in removed:
            console.print(f"[red]{table}: only in golden[/red] {b_rows[key]}")
        for key in sorted(set(a_rows) & set(b_rows)):
            fa, fb = _row_fields(a_rows[key]), _row_fields(b_rows[key])
            diffs = {n: (fa[n], fb[n]) for n in fa if fa[n] != fb.get(n)}
            if diffs:
                console.print(f"[cyan]{table} {key[1]}:[/cyan] " + ", ".join(
                    f"{n}: {a!r} != {b!r}" for n, (a, b) in diffs.items()))
                changed = True
        changed |= bool(added or removed)

    # 2. byte tier: page-by-page with masks
    a_raw, b_raw = ours._data, golden._data
    page_size = ours.page_size
    owners = _page_owner_map(golden if len(golden._data) >= len(ours._data) else ours)
    if len(a_raw) != len(b_raw):
        console.print(f"[cyan]size:[/cyan] ours {len(a_raw):,} vs golden {len(b_raw):,} bytes")
        changed = True
    n_pages = max(len(a_raw), len(b_raw)) // page_size
    for i in range(n_pages):
        pa = a_raw[i * page_size:(i + 1) * page_size]
        pb = b_raw[i * page_size:(i + 1) * page_size]
        if pa == pb:
            continue
        mask = _HEADER_MASK if i == 0 else _PAGE_MASK
        diff_offsets = [o for o in range(max(len(pa), len(pb)))
                        if (pa[o:o + 1] or b"\0") != (pb[o:o + 1] or b"\0")]
        unmasked = [o for o in diff_offsets
                    if not any(lo <= o < hi for lo, hi in mask)]
        owner = owners.get(i, "?")
        if unmasked:
            first, last = unmasked[0], unmasked[-1]
            console.print(
                f"[red]page {i}[/red] ({owner}): {len(unmasked)} bytes differ "
                f"(0x{first:03x}..0x{last:03x})")
            changed = True
        elif show_masked:
            console.print(f"[dim]page {i} ({owner}): masked-only differences "
                          f"({len(diff_offsets)} bytes)[/dim]")

    if not changed:
        console.print(f"[green]pdb equivalent[/green] "
                      f"({ours_path.name}: masked fields only)")
    return changed


# -- ANLZ --------------------------------------------------------------------


def _walk_anlz_sections(raw: bytes) -> list[tuple[str, bytes]]:
    """(fourcc, raw section bytes) pairs, walked independently of any parser.
    The 28-byte PMAI file header comes first as its own entry."""
    sections = [("PMAI", raw[:28])]
    off = 28
    while off + 12 <= len(raw):
        fourcc = raw[off:off + 4].decode("ascii", errors="replace")
        len_tag = int.from_bytes(raw[off + 8:off + 12], "big")
        if len_tag < 12:
            sections.append(("<garbage>", raw[off:]))
            break
        sections.append((fourcc, raw[off:off + len_tag]))
        off += len_tag
    return sections


def diff_anlz(console: Console, ours_path: Path, golden_path: Path) -> bool:
    a_secs = _walk_anlz_sections(ours_path.read_bytes())
    b_secs = _walk_anlz_sections(golden_path.read_bytes())
    changed = False
    a_seq = [t for t, _ in a_secs]
    b_seq = [t for t, _ in b_secs]
    if a_seq != b_seq:
        console.print(f"[cyan]tag sequence:[/cyan] ours {a_seq} vs golden {b_seq}")
        changed = True
    for i, ((ta, ba), (tb, bb)) in enumerate(zip(a_secs, b_secs)):
        if ta != tb or ba == bb:
            continue
        first = next(o for o in range(max(len(ba), len(bb)))
                     if o >= len(ba) or o >= len(bb) or ba[o] != bb[o])
        console.print(f"[red]{ta}[{i}][/red]: {len(ba):,} vs {len(bb):,} "
                      f"bytes, first diff at 0x{first:x}")
        changed = True
    if not changed:
        console.print(f"[green]ANLZ identical[/green] {ours_path.name}")
    return changed
