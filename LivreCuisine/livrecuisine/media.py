"""Photos (redimensionnement), images extraites des vidéos et transcription de la voix.

La transcription utilise faster-whisper, installé à part depuis l'onglet Réglages :
il fonctionne sans internet une fois le modèle téléchargé (la première fois).
"""

import importlib
import importlib.util
import io
import logging
import os
import site
import subprocess
import sys

from . import config

log = logging.getLogger("livrecuisine")

WHISPER_DIR = os.path.join(config.APP_DIR, "modeles_whisper")
_model = None
_model_name = None


def save_photo(src_path, dest_path, max_side=1600):
    """Recopie une image en JPEG de taille raisonnable."""
    from PIL import Image
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(dest_path, "JPEG", quality=88)
    return dest_path


def jpeg_bytes(img_or_path, max_side=1200):
    """Image (chemin ou PIL) -> octets JPEG, pour l'envoyer à Claude."""
    from PIL import Image
    im = Image.open(img_or_path) if isinstance(img_or_path, str) else img_or_path
    try:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return buf.getvalue()
    finally:
        if isinstance(img_or_path, str):
            im.close()


def can_read_video():
    return importlib.util.find_spec("av") is not None


def video_frames(path, count=6):
    """Quelques images réparties dans la vidéo (pour lire le texte affiché à l'écran)."""
    import av
    frames = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        if stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = (container.duration or 0) / 1_000_000
        if duration <= 0:
            return frames
        for i in range(count):
            t = duration * (i + 0.5) / count
            container.seek(int(t / stream.time_base), stream=stream, any_frame=False)
            for frame in container.decode(stream):
                frames.append(jpeg_bytes(frame.to_image(), max_side=1000))
                break
    return frames


# ------------------------------------------------------------------ transcription
def can_transcribe():
    return importlib.util.find_spec("faster_whisper") is not None


def transcribe(path, model_name="small"):
    """Texte prononcé dans la vidéo (langue détectée toute seule)."""
    global _model, _model_name
    from faster_whisper import WhisperModel
    if _model is None or _model_name != model_name:
        os.makedirs(WHISPER_DIR, exist_ok=True)
        _model = WhisperModel(model_name, device="cpu", compute_type="int8",
                              download_root=WHISPER_DIR)
        _model_name = model_name
    segments, info = _model.transcribe(path, vad_filter=True, beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    log.info("Transcription (%s, %.0f s) : %d caractères", info.language,
             info.duration or 0, len(text))
    return text


def python_console():
    """python.exe plutôt que pythonw.exe, pour lancer pip."""
    exe = sys.executable
    folder, name = os.path.split(exe)
    if name.lower().startswith("pythonw"):
        alt = os.path.join(folder, name[:6] + name[7:])
        if os.path.isfile(alt):
            return alt
    return exe


def install_transcription():
    """pip install faster-whisper. Renvoie (ok, texte de sortie)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [python_console(), "-m", "pip", "install", "--user", "faster-whisper"],
        capture_output=True, text=True, creationflags=flags)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        try:
            site.addsitedir(site.getusersitepackages())
        except Exception:
            pass
        importlib.invalidate_caches()
    return proc.returncode == 0, out
