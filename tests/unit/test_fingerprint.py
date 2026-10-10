import shutil
from pathlib import Path

import pytest

from cratedrop.analysis import fingerprint as fp

CLICK = Path(__file__).parent.parent / "fixtures" / "audio" / "click_120bpm.wav"

pytestmark = pytest.mark.skipif(not fp.available(), reason="fpcalc not installed")


def test_same_audio_different_bytes_is_duplicate(tmp_path):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    shutil.copy2(CLICK, a)
    shutil.copy2(CLICK, b)
    with open(b, "ab") as fh:  # different sha, identical audio
        fh.write(b"\x00" * 64)
    fa, fb = fp.fingerprint(a), fp.fingerprint(b)
    assert fp.similarity(fa, fb) > 0.95


def test_different_audio_is_not_duplicate(tmp_path):
    import numpy as np
    import soundfile as sf

    a = tmp_path / "a.wav"
    shutil.copy2(CLICK, a)
    rng = np.random.default_rng(1)
    noise = (rng.standard_normal(44100 * 30) * 0.2).astype("float32")
    b = tmp_path / "b.wav"
    sf.write(b, noise, 44100)
    assert fp.similarity(fp.fingerprint(a), fp.fingerprint(b)) < 0.6


def test_find_duplicates_groups(tmp_path):
    a, b, c = tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"
    shutil.copy2(CLICK, a)
    shutil.copy2(CLICK, b)
    with open(b, "ab") as fh:
        fh.write(b"\x01")
    import numpy as np
    import soundfile as sf
    rng = np.random.default_rng(2)
    sf.write(c, (rng.standard_normal(44100 * 30) * 0.2).astype("float32"), 44100)
    groups = fp.find_duplicates([(a, "sha-a"), (b, "sha-b"), (c, "sha-c")],
                                tmp_path / "proc")
    assert len(groups) == 1
    assert {p.name for p, _ in groups[0]} == {"a.wav", "b.wav"}
