"""RangeMusique – double-clique sur « Lancer RangeMusique.bat » pour démarrer."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rangemusique.gui import main  # noqa: E402

if __name__ == "__main__":
    main()
