"""Source checkout entrypoint; install dependencies into .venv first."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from arrow_y2k.__main__ import main

if __name__ == "__main__":
    main()
