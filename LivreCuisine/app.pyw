"""Livre de cuisine – double-clique sur « Lancer Livre de cuisine.bat » pour démarrer."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from livrecuisine.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
