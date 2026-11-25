from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..config import Config
from ..errors import BetterCoCError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bettercoc studio",
        description="betterCoC Vision Studio：只读预览、ROI/匹配叠加、模板试验与回放",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="固定测试集目录或录制会话目录，默认内置固定测试集",
    )
    parser.add_argument(
        "--fixtures",
        default="tests/fixtures/baseline",
        help="固定测试集目录，用于阈值试验",
    )
    parser.add_argument(
        "--workspace",
        default="runtime/studio",
        help="草稿与导出的工作目录",
    )
    parser.add_argument(
        "--screenshot",
        default=None,
        help="渲染主窗口到 PNG 后退出，用于无显示环境验证",
    )
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="使用 Qt offscreen 平台，不需要显示器",
    )
    return parser


def main(argv: list[str] | None = None, config: Config | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        if fonts.is_dir():
            os.environ.setdefault("QT_QPA_FONTDIR", str(fonts))
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "Vision Studio 需要可选依赖 PySide6：pip install -e .[studio]",
            file=sys.stderr,
        )
        return 2
    from .main_window import MainWindow

    source = args.source
    if source is None and Path(args.fixtures).is_dir():
        source = args.fixtures
    app = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        window = MainWindow(
            config=config,
            source_path=source,
            workspace=args.workspace,
            fixtures=args.fixtures,
        )
    except BetterCoCError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1
    if args.screenshot:
        target = window.render_screenshot(args.screenshot)
        print(f"窗口截图: {Path(target).resolve()}")
        window.close()
        app.processEvents()
        return 0
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
