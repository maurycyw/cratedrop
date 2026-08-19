from cratedrop.export.layout import dedupe, sanitize_component, usb_audio_path
from cratedrop.model import TrackMeta


def test_sanitize_strips_fat_forbidden():
    assert sanitize_component('A/B\\C:D*E?F"G<H>I|J') == "A_B_C_D_E_F_G_H_I_J"
    assert sanitize_component("  trailing.  ") == "trailing"
    assert sanitize_component("CON") == "Unknown"
    assert sanitize_component("") == "Unknown"


def test_usb_audio_path():
    meta = TrackMeta(source_path="/x/y/My Track.MP3", title="My Track",
                     artist="DJ: Test", album="Album?")
    assert usb_audio_path(meta) == "/Contents/DJ_ Test/Album_/My Track.mp3"


def test_usb_audio_path_defaults():
    meta = TrackMeta(source_path="/x/foo.flac", title="foo")
    assert usb_audio_path(meta) == "/Contents/Unknown Artist/Unknown Album/foo.flac"


def test_dedupe():
    taken = {"/contents/a/b/t.mp3", "/contents/a/b/t (2).mp3"}
    assert dedupe("/Contents/A/B/T.mp3", taken) == "/Contents/A/B/T (3).mp3"
    assert dedupe("/Contents/A/B/U.mp3", taken) == "/Contents/A/B/U.mp3"
