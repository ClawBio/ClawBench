import sys
from pathlib import Path

# Make HARNESS importable without packaging.
sys.path.insert(0, str(Path(__file__).resolve().parent / "HARNESS"))
