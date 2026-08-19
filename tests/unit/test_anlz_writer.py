import struct

import numpy as np
import pytest

from cratedrop.formats.anlz import writer
from cratedrop.formats.anlz.sections import anlz_folder_name
from cratedrop.model import (
    BeatGrid,
    CueKind,
    CuePoint,
    TrackAnalysis,
    TrackMeta,
    WaveformData,
)

from pyrekordbox.anlz import AnlzFile

USB_PATH = "/Contents/cratedrop/Test/Click.wav"


def _waveform(seconds: float = 120.0) -> WaveformData:
    n = int(seconds * 150)
    rng = np.random.default_rng(7)

    def arr(scale: float) -> tuple:
        return tuple((rng.random(n) * scale).tolist())

    return WaveformData(bins_per_second=150, peak=arr(0.9), rms=arr(0.5),
                        low=arr(0.4), mid=arr(0.1), high=arr(0.05))


@pytest.fixture(scope="module")
def analysis() -> TrackAnalysis:
    return TrackAnalysis(
        meta=TrackMeta(source_path="/x/click.wav", title="Click",
                       duration_ms=120_000.0, sample_rate=44100,
                       file_size=21_168_044),
        grid=BeatGrid.constant(bpm=120.0, first_beat_ms=500.0,
                               duration_ms=120_000.0),
        cues=(CuePoint(kind=CueKind.HOT, slot="A", time_ms=500.0),
              CuePoint(kind=CueKind.HOT, slot="B", time_ms=32_500.0, label="DROP"),
              CuePoint(kind=CueKind.HOT, slot="D", time_ms=96_500.0)),
        waveform=_waveform(),
    )


def test_dat_round_trip(analysis):
    data = writer.build_dat(analysis, USB_PATH)
    parsed = AnlzFile.parse(data)
    assert parsed.tag_types == ["PPTH", "PVBR", "PQTZ", "PWAV", "PWV2",
                                "PCOB", "PCOB"]
    assert parsed.file_header.len_file == len(data)
    assert parsed.get_tag("PPTH").get() == USB_PATH
    pqtz = parsed.get_tag("PQTZ")
    times = pqtz.get_times()
    assert len(times) == len(analysis.grid.beats)
    assert times[0] == pytest.approx(0.5)  # seconds
    assert set(pqtz.get_bpms()) == {120.0}


def test_ext_round_trip(analysis):
    data = writer.build_ext(analysis, USB_PATH)
    parsed = AnlzFile.parse(data)
    assert parsed.tag_types == ["PPTH", "PWV3", "PCOB", "PCOB", "PCO2", "PCO2",
                                "PQT2", "PWV5", "PWV4"]
    assert parsed.file_header.len_file == len(data)


def test_2ex_round_trip(analysis):
    data = writer.build_2ex(analysis, USB_PATH)
    parsed = AnlzFile.parse(data)
    assert parsed.tag_types == ["PPTH", "PWV7", "PWV6", "PWVC"]


def test_dat_pcob_entries(analysis):
    """Independent byte-level check of the hot-cue PCPT entries in the DAT
    (cues A-C only; D goes to the EXT)."""
    data = writer.build_dat(analysis, USB_PATH)
    idx = data.index(b"PCOB")
    len_tag = struct.unpack(">I", data[idx + 8:idx + 12])[0]
    num_cues = struct.unpack(">H", data[idx + 18:idx + 20])[0]
    assert num_cues == 2  # A and B; D is EXT-only
    assert len_tag == 24 + 2 * 56
    entries = data[idx + 24:idx + len_tag]
    seen = {}
    for off in range(0, len(entries), 56):
        assert entries[off:off + 4] == b"PCPT"
        hot_cue = struct.unpack(">I", entries[off + 12:off + 16])[0]
        time_ms = struct.unpack(">I", entries[off + 32:off + 36])[0]
        seen[hot_cue] = time_ms
    assert seen == {1: 500, 2: 32_500}


def test_ext_pco2_carries_all_hot_cues_and_label(analysis):
    data = writer.build_ext(analysis, USB_PATH)
    idx = data.index(b"PCO2")
    num_cues = struct.unpack(">H", data[idx + 16:idx + 18])[0]
    assert num_cues == 3  # A, B, D all present in PCO2
    assert "DROP".encode("utf-16-be") in data


def test_pvbr_native_length(analysis):
    data = writer.build_dat(analysis, USB_PATH)
    idx = data.index(b"PVBR")
    len_tag = struct.unpack(">I", data[idx + 8:idx + 12])[0]
    assert len_tag == 1620  # native Rekordbox length (401 entries + header)


def test_folder_name_shape():
    folder = anlz_folder_name(USB_PATH)
    part1, part2 = folder.split("/")
    assert part1.startswith("P") and len(part1) == 4
    assert len(part2) == 8
    # deterministic
    assert anlz_folder_name(USB_PATH) == folder


def test_write_anlz_files(analysis, tmp_path):
    written = writer.write_anlz(analysis, USB_PATH, tmp_path)
    assert set(written) == {"ANLZ0000.DAT", "ANLZ0000.EXT", "ANLZ0000.2EX"}
    for path in written.values():
        assert path.exists()
        AnlzFile.parse_file(path)  # must parse from disk too
