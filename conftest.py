import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
# Make HARNESS and the pinned skill-under-test importable without packaging.
sys.path.insert(0, str(_root / "HARNESS"))
sys.path.insert(0, str(_root / "SKILLS" / "clinical-variant-reporter"))
