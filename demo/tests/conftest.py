import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# demo/ only, deliberately: tools/ also has a validate.py and would shadow
# demo/validate.py on import.
sys.path.insert(0, str(REPO / "demo"))
