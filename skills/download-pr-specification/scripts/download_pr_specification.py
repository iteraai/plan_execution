#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
for path in (SCRIPT_DIR, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from plan_execution import planned_prs as _runtime

sys.modules[__name__] = _runtime


if __name__ == "__main__":
    raise SystemExit(_runtime.main())
