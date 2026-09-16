"""sys.path bridge so the soundness suite can reuse the e2e test harness."""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_E2E_TESTS = _HERE.parent / "e2e"
if str(_E2E_TESTS) not in sys.path:
    sys.path.insert(0, str(_E2E_TESTS))
