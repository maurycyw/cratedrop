"""Single choke-point for the fragmede/rekordbox-pdb dependency.

Everything in cratedrop imports pdb primitives from here. The library is
vendored (see _vendor/rekordbox_pdb/VENDORED.md) because PyPI forbids git
dependencies; this file is the only place that knows.
"""

from cratedrop._vendor.rekordbox_pdb import (  # noqa: F401
    Album,
    Artist,
    Artwork,
    Color,
    Database,
    ExtDatabase,
    ExtTableType,
    Genre,
    HistoryEntry,
    HistoryPlaylist,
    Key,
    Label,
    PlaylistEntry,
    PlaylistTreeNode,
    TableType,
    Track,
    decode_string,
)
from cratedrop._vendor.rekordbox_pdb.edit import PdbEditor  # noqa: F401
