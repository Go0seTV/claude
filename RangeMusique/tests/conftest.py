import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FFMPEG = shutil.which("ffmpeg")
CODECS = {
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "128k"],
    ".flac": ["-c:a", "flac"],
    ".m4a": ["-c:a", "aac", "-b:a", "128k"],
    ".ogg": ["-c:a", "libvorbis"],
    ".opus": ["-c:a", "libopus"],
    ".wma": ["-c:a", "wmav2"],
    ".wav": ["-c:a", "pcm_s16le"],
}
_cache = {}


@pytest.fixture(scope="session")
def audio_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("audio_src")


@pytest.fixture
def make_audio(audio_dir):
    """make_audio(path, seconds=3, freq=440, bitrate=None) -> crée un vrai fichier audio."""
    if not FFMPEG:
        pytest.skip("ffmpeg absent")

    def make(path, seconds=3, freq=440, bitrate=None):
        ext = os.path.splitext(str(path))[1].lower()
        args = list(CODECS[ext])
        if bitrate and "-b:a" in args:
            args[args.index("-b:a") + 1] = bitrate
        key = (ext, seconds, freq, tuple(args))
        if key not in _cache:
            out = os.path.join(audio_dir, f"{len(_cache)}{ext}")
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"sine=frequency={freq}:duration={seconds}", *args, out],
                           check=True)
            _cache[key] = out
        os.makedirs(os.path.dirname(str(path)), exist_ok=True)
        shutil.copy(_cache[key], str(path))
        return str(path)
    return make
