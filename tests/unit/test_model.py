from cratedrop.model import (
    BeatGrid,
    CueKind,
    CuePoint,
    CueSource,
    KeyResult,
    TrackAnalysis,
    TrackMeta,
    WaveformData,
    merge_cues,
)


def _analysis() -> TrackAnalysis:
    return TrackAnalysis(
        meta=TrackMeta(source_path="/x/track.mp3", title="T", artist="A",
                       duration_ms=120_000.0, sample_rate=44100, sha1="ab" * 20),
        grid=BeatGrid.constant(bpm=120.0, first_beat_ms=250.0, duration_ms=10_000.0),
        key=KeyResult(camelot="8A", standard="A minor", confidence=0.9, source="essentia"),
        cues=(CuePoint(kind=CueKind.HOT, slot="A", time_ms=250.0),),
        waveform=WaveformData(bins_per_second=150, peak=(0.5,), rms=(0.4,),
                              low=(0.1,), mid=(0.2,), high=(0.3,)),
        analyzer_versions={"beats": "test-1"},
    )


def test_json_round_trip():
    a = _analysis()
    b = TrackAnalysis.from_json(a.to_json())
    assert a == b


def test_constant_grid_expansion():
    g = BeatGrid.constant(bpm=120.0, first_beat_ms=0.0, duration_ms=2_000.0)
    assert [b.time_ms for b in g.beats] == [0.0, 500.0, 1000.0, 1500.0]
    assert [b.beat_in_bar for b in g.beats] == [1, 2, 3, 4]


def test_merge_deck_cue_wins_slot():
    heuristic = CuePoint(kind=CueKind.HOT, slot="A", time_ms=100.0)
    deck = CuePoint(kind=CueKind.HOT, slot="A", time_ms=999.0, source=CueSource.DECK)
    merged = merge_cues((deck,), (heuristic,))
    assert merged == (deck,)


def test_merge_heuristic_fills_free_slot():
    deck = CuePoint(kind=CueKind.HOT, slot="A", time_ms=999.0, source=CueSource.DECK)
    heuristic_b = CuePoint(kind=CueKind.HOT, slot="B", time_ms=100.0)
    merged = merge_cues((deck,), (heuristic_b,))
    assert set(merged) == {deck, heuristic_b}


def test_merge_incoming_deck_replaces_heuristic():
    heuristic = CuePoint(kind=CueKind.HOT, slot="A", time_ms=100.0)
    deck = CuePoint(kind=CueKind.HOT, slot="A", time_ms=200.0, source=CueSource.DECK)
    merged = merge_cues((heuristic,), (deck,))
    assert merged == (deck,)


def test_merge_memory_proximity():
    user = CuePoint(kind=CueKind.MEMORY, time_ms=1000.0, source=CueSource.DECK)
    near = CuePoint(kind=CueKind.MEMORY, time_ms=1300.0)
    far = CuePoint(kind=CueKind.MEMORY, time_ms=3000.0)
    merged = merge_cues((user,), (near, far))
    assert set(merged) == {user, far}
