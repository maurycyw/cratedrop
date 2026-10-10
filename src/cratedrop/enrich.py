"""Web enrichment: fill missing artwork and metadata from keyless public
APIs (Deezer, iTunes Search).

Policy: enrichment NEVER overwrites data that exists (file tags, folder-
derived names, manual overrides) — it only fills blanks. Results live in a
sha1-keyed sidecar plus a cached art JPEG; nothing is written into the
user's audio files. Matches below the score threshold are recorded as
candidates but not applied.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .model import TrackMeta

USER_AGENT = "cratedrop/0.1 (github.com/maurycyw/cratedrop)"
MIN_SCORE_DEFAULT = 0.72

# filename junk that poisons search queries
_JUNK = [
    re.compile(r"^\d{6,}_"),                    # beatport ids: 17399869_
    re.compile(r"\[[^\]]*\]"),                  # [TubeRipper.com], [wav 24]
    re.compile(r"\((?:official|lyric|audio|hd|hq)[^)]*\)", re.IGNORECASE),
    re.compile(r"\b(?:original mix|extended mix|radio edit)\b", re.IGNORECASE),
    re.compile(r"[_]+"),
    re.compile(r"\(\s*\)"),  # parens left empty by the strips above
]


def clean_query(title: str, artist: str = "") -> str:
    text = f"{artist} {title}".strip()
    for pat in _JUNK:
        text = pat.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class Candidate:
    artist: str
    title: str
    album: str
    art_url: str
    source: str
    score: float = 0.0


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def search_deezer(query: str) -> list[Candidate]:
    url = "https://api.deezer.com/search?" + urllib.parse.urlencode(
        {"q": query, "limit": 5})
    data = _get_json(url).get("data", [])
    return [Candidate(artist=r["artist"]["name"], title=r["title"],
                      album=r["album"]["title"],
                      art_url=r["album"].get("cover_big") or "",
                      source="deezer") for r in data]


def search_itunes(query: str) -> list[Candidate]:
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": query, "media": "music", "limit": 5})
    data = _get_json(url).get("results", [])
    out = []
    for r in data:
        art = (r.get("artworkUrl100") or "").replace("100x100", "600x600")
        out.append(Candidate(artist=r.get("artistName", ""),
                             title=r.get("trackName", ""),
                             album=r.get("collectionName", ""),
                             art_url=art, source="itunes"))
    return out


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_candidate(meta: TrackMeta, cand: Candidate) -> float:
    """Compare the candidate against what we know. When we have an artist,
    both fields must agree; when we only have a mangled title, match the
    whole cleaned string against 'artist title'."""
    query_title = clean_query(meta.title)
    if meta.artist:
        return 0.6 * _similarity(query_title, cand.title) + \
               0.4 * _similarity(meta.artist, cand.artist)
    combined = f"{cand.artist} {cand.title}"
    return max(_similarity(query_title, combined),
               _similarity(query_title, cand.title))


def find_match(meta: TrackMeta,
               min_score: float = MIN_SCORE_DEFAULT) -> Candidate | None:
    query = clean_query(meta.title, meta.artist)
    if len(query) < 4:
        return None
    candidates: list[Candidate] = []
    for search in (search_deezer, search_itunes):
        try:
            candidates += search(query)
        except Exception:  # noqa: BLE001 - a dead API just contributes nothing
            continue
        time.sleep(0.2)  # stay well under public rate limits
    if not candidates:
        return None
    for c in candidates:
        c.score = score_candidate(meta, c)
    best = max(candidates, key=lambda c: c.score)
    return best if best.score >= min_score and best.art_url else None


# ── sidecar storage ──────────────────────────────────────────────────────────


def _dir(processed_dir: Path) -> Path:
    return processed_dir / ".cratedrop" / "enrichment"


def load(processed_dir: Path, sha1: str) -> dict | None:
    path = _dir(processed_dir) / f"{sha1}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return None


def art_path(processed_dir: Path, sha1: str) -> Path:
    return _dir(processed_dir) / "art" / f"{sha1}.jpg"


def store(processed_dir: Path, sha1: str, cand: Candidate,
          art_bytes: bytes | None) -> None:
    d = _dir(processed_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha1}.json").write_text(json.dumps({
        "artist": cand.artist, "title": cand.title, "album": cand.album,
        "art_url": cand.art_url, "source": cand.source,
        "score": round(cand.score, 3)}, indent=1))
    if art_bytes:
        art_path(processed_dir, sha1).parent.mkdir(parents=True, exist_ok=True)
        art_path(processed_dir, sha1).write_bytes(art_bytes)


def download(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception:  # noqa: BLE001
        return None
