"""Unit tests for the glasses rig transcript parsing + mute gate."""
from live_brain.glasses_rig import MuteGate, parse_line


def test_parse_speech_with_lang():
    assert parse_line("- [09:26:02] (ru) Что это за агрегат?") == \
        ("utterance", "Что это за агрегат?")


def test_parse_speech_without_lang():
    assert parse_line("- [14:16:23] what is this thing") == \
        ("utterance", "what is this thing")


def test_parse_skips_echo_events_and_markers():
    assert parse_line("- [09:26:02] (ru) (echo?) Фото есть") is None
    assert parse_line("- [09:26:37] 🎥 local stream requested → rtmp://x") is None
    assert parse_line("- [09:26:37] 🔘 button camera short") is None
    assert parse_line("- [09:26:37] 📸 PHOTO_TAKEN (system camera) bytes=1") is None
    assert parse_line("> session connected 14:16:23") is None
    assert parse_line("") is None


def test_parse_frames_dir_from_live_line():
    line = ("- [09:26:48] 🎥 LOCAL STREAM LIVE, frames → "
            "/Users/x/captures/frames/local-2026-07-15-092648")
    assert parse_line(line) == \
        ("frames_dir", "/Users/x/captures/frames/local-2026-07-15-092648")


def test_mute_gate_cycle():
    g = MuteGate()
    assert g.admit("посмотри на клапан")            # default: respond
    assert not g.admit("так, хватит пока")           # mutes AND is not admitted
    assert not g.admit("бла бла сам с собой")        # muted
    assert g.admit("ассистент, что дальше?")         # unmutes AND is admitted
    assert g.admit("следующий шаг")
