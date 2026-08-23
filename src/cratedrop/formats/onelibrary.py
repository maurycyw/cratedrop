"""OneLibrary / Device Library Plus writer: PIONEER/rekordbox/exportLibrary.db.

The format the XDJ-AZ, Opus Quad, CDJ-3000X and Omnis Duo read (they ignore
the legacy export.pdb). SQLCipher-encrypted SQLite with a public static key.
Same strategy as the pdb: seed from a genuine Rekordbox-authored EMPTY
database (golden capture, rb 7.2.18) so every lookup/menu table is bit-true,
then insert rows mirroring the golden one-track example field for field.
Cues stay in the ANLZ files (the golden `cue` table is empty even with a hot
cue set); artwork is referenced as b<id>.jpg (the pdb uses a<id>.jpg).
"""

from __future__ import annotations

import datetime
import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from ..model import TrackAnalysis

KEY = "[ONELIBRARY-KEY-REDACTED]"
TEMPLATE = Path(str(files("cratedrop.formats.pdb") / "templates" / "empty-exportLibrary.db"))

# same codes Rekordbox uses in the pdb (verified across the user's library)
FILE_TYPE = {".mp3": 1, ".m4a": 4, ".wav": 11, ".aiff": 12, ".aif": 12, ".flac": 5}
MASTER_DB_ID = 1780350423   # rekordbox library id seen in golden; constant is fine
ANALYSED_BITS = 41          # constant in every golden row (105 = +phrase data)
CONTENT_LINK = 788224       # constant in every golden row


@dataclass
class OneLibTrack:
    analysis: TrackAnalysis
    usb_path: str          # /Contents/... (leading slash)
    anlz_dat_path: str     # /PIONEER/USBANLZ/.../ANLZ0000.DAT
    image_path: str | None # /PIONEER/Artwork/00001/b<n>.jpg or None
    date_added: str        # ISO date


def connect(path: Path):
    import sqlcipher3

    con = sqlcipher3.connect(str(path))
    con.execute(f"PRAGMA key = '{KEY}'")
    con.execute("PRAGMA cipher_compatibility = 4")
    return con


def _key_name(analysis: TrackAnalysis) -> str | None:
    if analysis.key is None:
        return None
    from .pdb.builder import key_name

    return key_name(analysis.key.camelot)


def write_onelibrary(out_dir: Path, tracks: list[OneLibTrack],
                     playlists: list[tuple[str, list[int]]],
                     template: Path = TEMPLATE) -> list[Path]:
    """Write exportLibrary.db (+ -wal/-shm as Rekordbox ships them) into
    out_dir. playlists: (name, [track indexes into `tracks`]). Returns the
    files written."""
    db = out_dir / "exportLibrary.db"
    for junk in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
        junk.unlink(missing_ok=True)
    shutil.copy2(template, db)
    con = connect(db)
    cur = con.cursor()

    lookup_cache: dict[tuple[str, str], int] = {}

    def get_or_create(table: str, name: str | None, id_col: str, **extra) -> int | None:
        if not name:
            return None
        key = (table, name)
        if key in lookup_cache:
            return lookup_cache[key]
        row = cur.execute(f"SELECT {id_col} FROM [{table}] WHERE name = ?", (name,)).fetchone()
        if row:
            lookup_cache[key] = row[0]
            return row[0]
        cols = ["name"] + list(extra)
        vals = [name] + list(extra.values())
        cur.execute(f"INSERT INTO [{table}] ({', '.join(cols)}) VALUES ({', '.join('?' * len(vals))})", vals)
        lookup_cache[key] = cur.lastrowid
        return cur.lastrowid

    content_ids: list[int] = []
    for i, t in enumerate(tracks, start=1):
        m = t.analysis.meta
        artist_id = get_or_create("artist", m.artist, "artist_id", nameForSearch=None)
        album_id = get_or_create("album", m.album, "album_id", artist_id=artist_id,
                                 image_id=None, isComplation=0, nameForSearch=None)
        genre_id = get_or_create("genre", m.genre, "genre_id")
        key_id = get_or_create("key", _key_name(t.analysis), "key_id")
        image_id = None
        if t.image_path:  # image table keys by path, not name
            key = ("image", t.image_path)
            if key not in lookup_cache:
                row = cur.execute("SELECT image_id FROM image WHERE path = ?",
                                  (t.image_path,)).fetchone()
                if row is None:
                    cur.execute("INSERT INTO image (path) VALUES (?)", (t.image_path,))
                    row = (cur.lastrowid,)
                lookup_cache[key] = row[0]
            image_id = lookup_cache[key]
        ext = Path(t.usb_path).suffix.lower()
        cur.execute(
            "INSERT INTO content (content_id, title, titleForSearch, subtitle, bpmx100, length, "
            "trackNo, discNo, artist_id_artist, artist_id_remixer, artist_id_originalArtist, "
            "artist_id_composer, artist_id_lyricist, album_id, genre_id, label_id, key_id, "
            "color_id, image_id, djComment, rating, releaseYear, releaseDate, dateCreated, "
            "dateAdded, path, fileName, fileSize, fileType, bitrate, bitDepth, samplingRate, "
            "isrc, djPlayCount, isHotCueAutoLoadOn, isKuvoDeliverStatusOn, kuvoDeliveryComment, "
            "masterDbId, masterContentId, analysisDataFilePath, analysedBits, contentLink, "
            "hasModified, cueUpdateCount, analysisDataUpdateCount, informationUpdateCount) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, m.title, None, "",
             round(t.analysis.grid.bpm * 100) if t.analysis.grid else 0,
             round(m.duration_ms / 1000), m.track_no, 0,
             artist_id, None, None, None, 0,
             album_id, genre_id, None, key_id, 0, image_id,
             "", 0, m.year, "", t.date_added, t.date_added,
             t.usb_path, Path(t.usb_path).name, m.file_size, FILE_TYPE.get(ext, 1),
             m.bitrate, 16, m.sample_rate,
             "", 0, 1, 1, "",
             MASTER_DB_ID, 50_000_000 + i, t.anlz_dat_path, ANALYSED_BITS, CONTENT_LINK,
             0, None, None, None))
        content_ids.append(i)

    for seq, (name, idxs) in enumerate(playlists):
        cur.execute("INSERT INTO playlist (sequenceNo, name, image_id, attribute, playlist_id_parent) "
                    "VALUES (?,?,?,?,?)", (seq, name, None, 0, 0))
        pid = cur.lastrowid
        for n, idx in enumerate(idxs):
            cur.execute("INSERT INTO playlist_content (playlist_id, content_id, sequenceNo) VALUES (?,?,?)",
                        (pid, content_ids[idx], n))

    cur.execute("UPDATE property SET numberOfContents = ?, createdDate = ?",
                (len(tracks), datetime.date.today().isoformat()))
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    return [p for p in (db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"))
            if p.exists()]
