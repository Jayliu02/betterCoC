from __future__ import annotations

import json
from pathlib import Path


def read_state(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update_state(path: str | Path, **values) -> dict:
    target = Path(path)
    data = read_state(target)
    data.update(values)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data
