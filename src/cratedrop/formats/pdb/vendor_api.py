"""Single choke-point for the fragmede/rekordbox-pdb dependency.

Everything in cratedrop imports pdb primitives from here, never from
`rekordbox_pdb` directly — if upstream churns or we need to vendor a patched
copy, this is the only file that changes.
"""

from rekordbox_pdb import (  # noqa: F401
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
from rekordbox_pdb.edit import PdbEditor  # noqa: F401
