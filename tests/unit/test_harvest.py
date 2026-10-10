from pathlib import Path

from cratedrop.deploy.harvest import extract_cues, extract_ppth
from cratedrop.formats.anlz import writer
from cratedrop.model import (
    BeatGrid,
    CueKind,
    CuePoint,
    CueSource,
    TrackAnalysis,
    TrackMeta,
)

GOLDEN_CLICK_EXT = (Path(__file__).parent.parent / "fixtures" / "golden" / "click"
                    / "PIONEER" / "USBANLZ" / "P026" / "0000B17C" / "ANLZ0000.EXT")


def test_extract_from_golden_rekordbox_ext():
    """The golden click EXT carries a native hot cue A at 499 ms, labeled."""
    raw = GOLDEN_CLICK_EXT.read_bytes()
    cues, loops = extract_cues(raw)
    assert loops == 0
    hot_a = [c for c in cues if c.kind == CueKind.HOT and c.slot == "A"]
    assert len(hot_a) == 1
    assert hot_a[0].time_ms == 499.0
    assert hot_a[0].label == "1.1Bars"
    assert hot_a[0].source == CueSource.DECK


def test_extract_ppth_from_golden():
    raw = GOLDEN_CLICK_EXT.read_bytes()
    assert extract_ppth(raw) == "/Contents/UnknownArtist/UnknownAlbum/click_120bpm.wav"


def test_round_trip_through_our_writer():
    """Cues written by our own writer are recoverable by the harvester."""
    analysis = TrackAnalysis(
        meta=TrackMeta(source_path="/x.wav", title="X", duration_ms=60_000.0,
                       sample_rate=44100),
        grid=BeatGrid.constant(bpm=120.0, first_beat_ms=0.0, duration_ms=60_000.0),
        cues=(CuePoint(kind=CueKind.HOT, slot="A", time_ms=1_000.0, label="KICK IN"),
              CuePoint(kind=CueKind.HOT, slot="D", time_ms=44_000.0, label="OUTRO")),
    )
    ext = writer.build_ext(analysis, "/Contents/A/B/x.wav")
    cues, _ = extract_cues(ext)
    by_slot = {c.slot: c for c in cues if c.kind == CueKind.HOT}
    assert by_slot["A"].time_ms == 1_000.0 and by_slot["A"].label == "KICK IN"
    assert by_slot["D"].time_ms == 44_000.0


def test_memory_and_loop_round_trip():
    """Memory cues and loops (hot + memory) survive writer -> harvester."""
    analysis = TrackAnalysis(
        meta=TrackMeta(source_path="/x.wav", title="X", duration_ms=60_000.0,
                       sample_rate=44100),
        grid=BeatGrid.constant(bpm=120.0, first_beat_ms=0.0, duration_ms=60_000.0),
        cues=(CuePoint(kind=CueKind.MEMORY, time_ms=4_000.0),
              CuePoint(kind=CueKind.MEMORY, time_ms=16_000.0, loop_out_ms=18_000.0),
              CuePoint(kind=CueKind.HOT, slot="B", time_ms=30_000.0,
                       label="LOOP8", loop_out_ms=34_000.0)),
    )
    for build in (writer.build_dat, writer.build_ext):
        cues, loops = extract_cues(build(analysis, "/Contents/A/B/x.wav"))
        assert loops >= 1
        mem = sorted((c for c in cues if c.kind == CueKind.MEMORY),
                     key=lambda c: c.time_ms)
        assert [c.time_ms for c in mem] == [4_000.0, 16_000.0]
        assert mem[0].loop_out_ms is None
        assert mem[1].loop_out_ms == 18_000.0
        hot_b = next(c for c in cues if c.kind == CueKind.HOT and c.slot == "B")
        assert hot_b.loop_out_ms == 34_000.0


def test_loop_json_round_trip():
    c = CuePoint(kind=CueKind.HOT, slot="A", time_ms=1.0, loop_out_ms=2_000.0,
                 source=CueSource.DECK)
    a = TrackAnalysis(meta=TrackMeta(source_path="/x", title="t"), cues=(c,))
    assert TrackAnalysis.from_json(a.to_json()).cues[0].loop_out_ms == 2_000.0
