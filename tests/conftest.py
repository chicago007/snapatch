"""pytest — diver(engines/diver) import 경로."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DIVER = _ROOT / "engines" / "diver"

if str(_DIVER) not in sys.path:
    sys.path.insert(0, str(_DIVER))
