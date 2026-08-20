from cratedrop.enrich import Candidate, clean_query, score_candidate
from cratedrop.model import TrackMeta


def test_clean_query_strips_junk():
    assert clean_query("17399869_Say My Name_(Original Mix)") == "Say My Name"
    assert clean_query("Lauryn Hill - That Thing (Acapella) [TubeRipper.com]") \
        == "Lauryn Hill - That Thing (Acapella)"
    assert clean_query("Venezia  [wav 24]", "Sandro Cardio") == "Sandro Cardio Venezia"


def test_score_with_known_artist():
    meta = TrackMeta(source_path="/x.wav", title="Speaker Freaker (Original Mix)",
                     artist="Sara Landry")
    good = Candidate(artist="Sara Landry & Diøn", title="Speaker Freaker",
                     album="", art_url="u", source="t")
    bad = Candidate(artist="Someone Else", title="Completely Different Song",
                    album="", art_url="u", source="t")
    assert score_candidate(meta, good) > 0.7
    assert score_candidate(meta, bad) < 0.4


def test_score_titleonly_matches_combined():
    meta = TrackMeta(source_path="/x.wav", title="Lilly Allen - Not Fair (DNNS EDIT)")
    cand = Candidate(artist="Lily Allen", title="Not Fair", album="",
                     art_url="u", source="t")
    assert score_candidate(meta, cand) > 0.55


def test_enrichment_fills_blanks_only(tmp_path):
    import shutil
    from pathlib import Path

    from cratedrop import enrich
    from cratedrop.export.builder import analyze_track

    staging = tmp_path / "staging"
    processed = tmp_path / "processed"
    staging.mkdir()
    click = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"
    dest = staging / "mystery track.wav"
    shutil.copy2(click, dest)

    from cratedrop.audio.tags import sha1_file
    sha = sha1_file(dest)
    enrich.store(processed, sha,
                 Candidate(artist="Web Artist", title="Mystery Track",
                           album="Web Album", art_url="u", source="test",
                           score=0.9), art_bytes=None)

    analysis, _ = analyze_track(dest, processed, staging)
    assert analysis.meta.artist == "Web Artist"   # blank -> filled
    assert analysis.meta.album == "Web Album"
    assert analysis.meta.title == "mystery track"  # existing title untouched
