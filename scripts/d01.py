"""Project-local CLI without installing into a global Python environment."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from d01.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
