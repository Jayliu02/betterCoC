# Stage 3 报告：betterCoC Vision Studio（V0.4.0）

> 完成时间：2026-11-25
> 对应方案：`betterCoC_next_stage_plan.zh-CN.md` 第 5 节
> 判定：**通过**（S3.1–S3.6 全部落地；134 个测试通过；offscreen 渲染验证三个页面）
> 版本：0.4.0

## 1. 目标

提供只读的视觉调试界面：静态/会话预览、ROI 与匹配叠加、框选模板与阈值试验、会话回放与事件定位、
设备只读预览与帧龄显示。GUI 是可选依赖，CLI 与任务行为不变；所有预览与回放路径不发送任何设备输入。

## 2. 实际修改

新增 `bettercoc/studio/`：

| 文件 | 作用 |
| --- | --- |
| `studio/app.py` | `bettercoc studio` 入口、参数解析、offscreen/字体处理、`--screenshot` |
| `studio/main_window.py` | 左侧导航、页面栈、数据源切换、帧导航、后台任务调度、窗口截图、关闭释放 |
| `studio/canvas.py` | `ImageCanvas`：等比缩放、留白、滚轮缩放、悬停坐标、框选、叠加绘制 |
| `studio/geometry.py` | 画布拟合与坐标换算（纯函数，可单测） |
| `studio/source.py` | `FixtureSource` / `SessionSource` / `LiveSource` 与自动识别 |
| `studio/recognition.py` | 识别行模型、阈值试验（误检/漏检）、草稿导出 |
| `studio/vision_panel.py` | Vision 页：画面、识别项、结果表、状态颜色、ROI/bbox 叠加 |
| `studio/template_editor.py` | Template 页：框选、预览、ROI、阈值试验、草稿导出 |
| `studio/replay_panel.py` | Replay 页：会话加载、逐帧事件、复现识别与差异表 |
| `studio/log_panel.py` | Logs 页：事件过滤、搜索、导出 JSONL |
| `studio/settings_panel.py` | Settings 页：只读配置与资源信息 |
| `studio/worker.py` | `BackgroundRunner`：单线程 QThreadPool、有界待处理队列、关闭等待 |
| `studio/widgets.py` | 表格与状态配色辅助 |

修改：`cli.py` 增加 `studio` 子命令；`pyproject.toml` 增加 `[studio]` 可选依赖与 0.4.0 版本；
`bettercoc/__init__.py` 0.4.0；`README.md` 增加 Studio 用法；新增 `docs/vision-studio.md`。

未修改：`resources.py`、任务模块、`recovery.py`、`Vision`/`Context` 的既有契约。Studio 只通过
`build_vision`、`FrameProvider`/`Capture`、`ReplaySession` 读取数据。

## 3. 命令与结果

| 命令 | 结果 |
| --- | --- |
| `pip install -e ".[studio]"`（等价 `pip install PySide6`） | PySide6 6.12.0 安装成功 |
| `python -m unittest discover -s tests` | 134 tests, OK |
| `python -m bettercoc studio --screenshot runtime/studio/main.png --offscreen` | 退出码 0，1600x940 PNG，含 32 帧测试集、识别结果表、叠加框 |
| `tests/test_studio.py` 的窗口测试 | 加载 32 帧、切 5 个页面、框选、导出草稿、抓图、关闭后 `pending=0` |
| 模板阈值试验（框选 home_attack 按钮，4 个阈值） | 32 帧统计：0.86 阈值下命中 6 / 漏检 1 / 误检 4 / 正确排除 12 |
| `bettercoc replay`（Stage 2 会话） | 60/60 一致，0 差异 |

页面截图（offscreen 渲染，本地文件）：

- `runtime/studio/main.png`：Vision 页，识别结果表含 `matched`/`coordinate_only`/`miss`/`unknown`
- `runtime/studio/template.png`：Template 页，选区、模板预览、阈值试验表
- `runtime/studio/replay.png`：Replay 页，会话帧事件表与回放差异区

## 4. 验收判定（方案 5.4）

| 验收门槛 | 判定 | 证据 |
| --- | --- | --- |
| 不改 Python 源码即可完成静态模板裁剪、ROI 调整、阈值试验与草稿导出 | 通过 | Template 页框选 + ROI 输入 + 试验 + `export_draft`；`test_export_draft_does_not_touch_assets` |
| GUI 与 CLI 对同一静态帧和配置给出一致识别结果 | 通过 | `test_gui_rows_match_direct_vision` 逐项对比状态与分数 |
| 原始尺寸、等比缩放、非等比窗口、留白四种画布坐标往返误差 ≤1 canonical 像素 | 通过 | `CanvasGeometryTest` 四个用例 + 往返断言 |
| 静态及 mock 预览连续运行 10 分钟，无崩溃、无无界队列增长；关闭后 worker 退出 | 部分通过 | 队列上限、关闭等待、多页面切换与抓图回归通过；**10 分钟长跑未实测** |
| 无设备时 GUI 可启动，离线功能可用 | 通过 | 默认数据源为固定测试集；offscreen 启动与截图不连设备 |
| 所有预览和回放路径不发出触控、按键或应用重启指令 | 通过 | 源码扫描测试禁止 `controller.`/`input tap`/`keyevent`/`force-stop`；LiveSource 只用只读截图 |

## 5. 未完成项

- 10 分钟连续运行与内存曲线未实测；只做了队列上限与关闭释放测试。
- 设备只读预览未在本机实际连接验证（需要人工点击“连接设备只读预览”）。
- 高 DPI/多显示器缩放下未验证；画布坐标以逻辑像素计算，未做 fractional DPI 专项测试。
- Logs 页没有分页；事件很多时表格一次性填充。
- 没有实现拖动平移、区间缩放、模板一键合并到正式资源。

## 6. 已知风险

1. `--screenshot` 在真实桌面会短暂显示窗口；只在 offscreen 下用于回归。
2. 事件表加载全部事件，超大会话（数万事件）会有渲染开销；`EventLog` 上限 5000 条，录制侧已受限。
3. Template 页的试验基于 `tests/fixtures/baseline`（32 帧、单账号 UI），阈值结论不能直接外推到其他分辨率。
4. 草稿导出不校验名称冲突：重复导出会覆盖同目录同名文件（只在 `runtime/studio/drafts` 内）。
5. Studio 依赖 PySide6 6.6+；Qt 版本变化可能影响 offscreen 字体渲染（已用 `QT_QPA_FONTDIR` 处理无字体环境）。

## 7. 下一阶段建议

Stage 4（通用测试任务运行时，V0.5.0）是可选工作包。若要启动，建议顺序：

1. 先把 Studio 的模板试验结果接入诊断事件（`event_type=recognition` 已有字段），便于对比不同阈值的历史结论。
2. TaskRegistry 只注册 mock/自有测试动作；复用 Stage 2 的 `EventLog`、`TaskResult` 与取消令牌，不扩展到真实游戏调度。
3. 生命周期状态建议直接复用 `StateStatus` 与 `ErrorCode` 的命名，避免第二套枚举。
4. Stage 5 的 scrcpy 评估已被基线触发（ADB 截图占周期约 90%），但应先验证长稳与多分辨率再改采集链路。
