from pathlib import Path

import numpy as np
import pytest

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
