from __future__ import annotations

_GOLD = 0
_ELIXIR = 0
_DARK = 0
_GOLD_MAX = 0
_ELIXIR_MAX = 0
_DARK_MAX = 0
_WALLS_REMAINING: int | None = None
_WALLS_UPGRADED: int | None = None
_WALLS_COMPLETE = False
_LAST_KEY: tuple | None = None


def set_max(
    gold_max: int | None = None,
    elixir_max: int | None = None,
    dark_max: int | None = None,
    redraw: bool = True,
) -> None:
    global _GOLD_MAX, _ELIXIR_MAX, _DARK_MAX
    if gold_max is not None:
        _GOLD_MAX = int(gold_max)
    if elixir_max is not None:
        _ELIXIR_MAX = int(elixir_max)
    if dark_max is not None:
        _DARK_MAX = int(dark_max)
    if redraw:
        update(force=True)


def set_walls(
    remaining: int | None = None,
    upgraded: int | None = None,
    complete: bool | None = None,
    reason: str = "",
    redraw: bool = True,
) -> None:
    global _WALLS_REMAINING, _WALLS_UPGRADED, _WALLS_COMPLETE
    _WALLS_REMAINING = None if remaining is None else int(remaining)
    if upgraded is not None:
        _WALLS_UPGRADED = int(upgraded)
    if complete is not None:
        _WALLS_COMPLETE = bool(complete)
    if redraw:
        update(reason=reason)


def update(
    gold: int | None = None,
    elixir: int | None = None,
    dark: int | None = None,
    reason: str = "",
    force: bool = False,
) -> None:
    global _GOLD, _ELIXIR, _DARK, _LAST_KEY
    if gold is not None:
        _GOLD = int(gold)
    if elixir is not None:
        _ELIXIR = int(elixir)
    if dark is not None:
        _DARK = int(dark)
    key = (
        _GOLD,
        _ELIXIR,
        _DARK,
        _GOLD_MAX,
        _ELIXIR_MAX,
        _DARK_MAX,
        _WALLS_REMAINING,
        _WALLS_UPGRADED,
        _WALLS_COMPLETE,
    )
    if key == _LAST_KEY and not force:
        return
    _LAST_KEY = key
    gold_max = f"{_GOLD_MAX:,}" if _GOLD_MAX > 0 else "?"
    elixir_max = f"{_ELIXIR_MAX:,}" if _ELIXIR_MAX > 0 else "?"
    dark_max = f"{_DARK_MAX:,}" if _DARK_MAX > 0 else "?"
    lines = [
        "",
        "+---------------- 资源状态 ----------------+",
        f"| 金币 {_GOLD:,} / {gold_max}",
        f"| 圣水 {_ELIXIR:,} / {elixir_max}",
        f"| 暗黑 {_DARK:,} / {dark_max}",
    ]
    if _WALLS_COMPLETE:
        lines.append("| 城墙 已无可升级项")
    elif _WALLS_REMAINING is not None:
        lines.append(f"| 城墙 可升级 {_WALLS_REMAINING} 段")
    else:
        lines.append("| 城墙 可升级数量未知")
    if _WALLS_UPGRADED is not None:
        lines.append(f"| 本次升级 {_WALLS_UPGRADED} 段")
    if reason:
        lines.append(f"| {reason:<38} |")
    lines.append("+------------------------------------------+")
    print("\n".join(lines), flush=True)


def format_line(gold: int, elixir: int, dark: int) -> str:
    return f"金币 {gold:,} | 圣水 {elixir:,} | 暗黑 {dark:,}"
