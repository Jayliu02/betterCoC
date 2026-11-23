from __future__ import annotations

import uuid
from pathlib import Path


def make_temp_dir(prefix: str) -> Path:
    base = Path("runtime/test-tmp").resolve()
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{prefix}-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    return target
