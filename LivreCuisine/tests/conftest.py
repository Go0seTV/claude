import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def make_jpeg(tmp_path):
    """make_jpeg(nom, couleur) -> chemin d'une vraie image JPEG."""
    from PIL import Image

    def make(name="photo.jpg", color=(200, 120, 60), size=(800, 600)):
        path = tmp_path / name
        Image.new("RGB", size, color).save(path, "JPEG")
        return str(path)
    return make
