import pytest

from rangemusique import tagio

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
       b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
       b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")

TAGS = {"title": "Take My Breath Away", "artist": "Berlin", "albumartist": "Berlin",
        "album": "Top Gun", "track": 3, "tracktotal": 10, "disc": None, "disctotal": None,
        "year": "1986", "genre": "Pop"}


@pytest.mark.parametrize("ext", [".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wma", ".wav"])
def test_roundtrip(tmp_path, make_audio, ext):
    path = make_audio(tmp_path / f"song{ext}")
    old, info, has_cover = tagio.read(path)
    assert not old["title"] and info.duration > 2
    tagio.write(path, TAGS, cover=PNG)
    new, info, has_cover = tagio.read(path)
    for k in ("title", "artist", "albumartist", "album", "genre"):
        assert new[k] == TAGS[k], (ext, k)
    assert new["year"].startswith("1986")
    assert new["track"] == 3
    if ext != ".wma":
        assert has_cover
        assert new["tracktotal"] == 10 or ext == ".wma"
    assert info.lossless == (ext in (".flac", ".wav"))

    # restauration (annulation) : les champs vides sont effacés
    tagio.write(path, {"title": "Ancien titre"}, clear_empty=True)
    back, _, _ = tagio.read(path)
    assert back["title"] == "Ancien titre"
    assert not back["album"] and not back["artist"] and not back["track"]
