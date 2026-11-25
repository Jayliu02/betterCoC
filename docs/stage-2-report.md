# Stage 2 报告：核心运行时与诊断（V0.3.0）

> 完成时间：2026-11-25
> 对应方案：`betterCoC_next_stage_plan.zh-CN.md` 第 4 节
> 判定：**通过**（4.1–4.4 全部落地；116 个测试通过；离线回放 60/60 复现；Stage 1 基线保持 106/107）
> 版本：0.3.0

## 1. 目标

给识别结果加帧身份、给状态加来源与新鲜度、给失败加结构化诊断、给问题加离线回放。保留
`Context.screen()`、`Vision`、`Locator`、任务默认参数与 `resources.py` 的全局资源流程不变，
新增能力通过新模块和适配器接入。

## 2. 实际修改

新增模块：

| 文件 | 作用 |
| --- | --- |
| `bettercoc/frame.py` | `Frame`、`FrameProvider`、只读帧图像、过期判定 |
| `bettercoc/events.py` | `Event`、`EventLog`、`EventType`、`ErrorCode`、异常分类 |
| `bettercoc/recorder.py` | 只读诊断会话录制（manifest / frames / events.jsonl / report.json）与上限 |
| `bettercoc/replay.py` | 离线回放、录制结果对比、资源指纹漂移提示 |
| `bettercoc/state_store.py` | 观测/诊断状态：来源、新鲜度、容量判定、原子写入、历史格式兼容 |
| `bettercoc/jsonio.py` | 原子 JSON 写入、JSONL 读取 |

修改：

| 文件 | 修改 | 兼容性 |
| --- | --- | --- |
| `bettercoc/image.py` | `Screen` 增加 `frame_id`、`sequence`（都有默认值） | 现有 `Screen(...)` 构造与读取不变 |
| `bettercoc/result.py` | `Match` 增加 `frame_id`、`threshold`、`status`；新增 `RecognitionStatus` | 新增字段均有默认值 |
| `bettercoc/vision.py` | point 无 `check` 时返回 `coordinate_only`；`find_all` 回填 `frame_id`/`threshold` | 返回值仍为 `list[Match]` |
| `bettercoc/context.py` | `screen()` 走 `FrameProvider`；新增 `capture_frame`/`current_frame`/`refresh_frame`/`frame_age`/`find_in`/`find_all_in` | `screen()` 签名与返回类型不变 |
| `bettercoc/errors.py` | 新增 `FrameStaleError` | 纯新增 |
| `bettercoc/app.py` | 传递 `runtime.frame_stale_after`（默认 2 秒） | 缺省行为不变 |
| `bettercoc/cli.py` | 新增 `record` / `replay` / `state` 子命令 | 纯新增 |
| `bettercoc/__init__.py`、`pyproject.toml` | 0.2.1 → 0.3.0 | — |
| `docs/architecture.md` | 新增帧、识别语义、诊断事件、录制回放、状态存储章节 | 纯追加 |
| `README.md` | 新增诊断与回放用法、模块表条目 | 纯追加 |

未改动：`resources.py` 的全局资源流程、三个任务的调度与默认参数、`recovery.py` 的恢复动作。
任务代码里没有新增任何游戏恢复或自动执行逻辑。

## 3. 命令与结果

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests` | 116 tests, OK, 21.0s |
| `python -m bettercoc record --frames 2` | 会话生成：2 帧、62 事件（1 session + 2 capture + 各帧 30 项识别） |
| `python -m bettercoc --config config/mumu.yaml replay <session>` | 帧 2、检查 60、与录制对比 60、不一致 0，退出码 0 |
| `python -m bettercoc --config config/mumu.yaml state` | 读取历史 `runtime/resource-state.json`，8 个键全部标为 `cached`、无观测时间 |
| `python -m bettercoc --config config/mumu.yaml baseline --iterations 20` | 32 帧 / 107 项：106 通过、1 已知缺陷，与 Stage 1 一致 |

新增测试分布：

| 测试文件 | 数量 | 覆盖 |
| --- | --- | --- |
| `tests/test_frame.py` | 15 | 帧顺序、mock/folder/static、坐标往返、只读图像、过期帧、同帧识别、`FrameStaleError` |
| `tests/test_diagnostics.py` | 15 | 事件字段与 JSONL、有界日志与丢弃计数、错误分类、录制文件结构、帧数上限、回放复现/确定性/漂移 |
| `tests/test_state_store.py` | 12 | 缺失≠0、合法零值、过期、配置兜底、估算来源、容量判定、新格式往返、历史格式、损坏文件、写失败保护 |

## 4. 性能影响

本次没有改变采集路径，`bettercoc baseline` 的识别耗时与 Stage 1 一致（模板匹配 P50 约 45ms、
数字 1.2ms、颜色校验 0.02ms、ADB 截图 639–703ms）。新增开销：

- 每帧记录：PNG 落盘约 30–60ms/帧（1920x1080），只发生在 `record` 会话。
- 每个识别项记录一个事件：JSONL 追加 + 内存环形缓冲，微秒级。
- 帧对象本身只增加一个只读视图，不复制像素。

`record` 默认从固定测试集取帧，不接触设备；`--live` 才做只读截图。

## 5. 未完成项

- 事件日志还没有接入任务的 `Context.find`：任务运行时不会自动产生诊断事件，目前由 `record` 显式驱动。
  这是有意的边界，避免改动任务行为；Stage 3 的 Studio 会消费录制会话。
- `StateStore` 没有替换 `resources.GOLD/ELIXIR/...`，按方案要求只建立独立模型。
- 录制只保存 canonical 帧，不保存原始设备帧；换分辨率排查时无法还原原始像素。
- `--live` 录制已用 1 帧验证（`record --live --frames 1` → `replay` 30/30 一致），未做长时间设备录制。
- 事件里没有 `run_id` 关联的全局 trace 视图；CLI 只提供 `state`/`replay` 两个查看入口。

## 6. 已知风险

1. `find_in` 的过期阈值默认 2 秒，ADB 单帧 640ms，连续多次识别可能逼近阈值；任务代码尚未使用
   `find_in`，接入时需要按场景设置 `max_age`。
2. 回放的分数容差固定 `1e-3`，来自事件 JSON 的 4 位小数；如果将来改变事件精度，需要同步调整。
3. 录制会话占用磁盘：默认上限 200 帧 / 200MB，超出会截断并记 `truncated`，但不会自动清理旧会话。
4. `Screen` 级别没有变化：`Screen.image` 仍是可写数组，只读约束只在 `Frame` 上；第三方代码直接改
   `Screen.image` 不受限制。
5. 事件与状态文件都使用原子替换，但 Windows 上并发写同一路径仍可能互相覆盖；单进程使用没有问题。

## 7. 验收判定（方案 4.5）

| 验收项 | 判定 | 证据 |
| --- | --- | --- |
| 每个识别结果可关联唯一输入帧 | 通过 | `Match.frame_id`、`Screen.frame_id`、`EventLog.recognition`；`test_same_frame_recognition_shares_frame_id` |
| 读取失败、未知状态与合法零值可区分 | 通过 | `test_missing_is_not_zero`、`test_zero_is_a_real_value`、`test_corrupt_file_sets_load_error` |
| 模板不匹配、设备断开等异常有明确诊断，不新增游戏恢复动作 | 通过 | `ErrorCode` + `classify_error` 测试；未修改 `recovery.py` 与任务 |
| 离线回放可复现标注集识别结果，且无 ADB 输入 | 通过 | `replay` 60/60 一致；`ReplaySession` 不创建 Capture；`test_replay_reproduces_recorded_results` |
| Stage 1 基线通过，更新架构文档 | 通过 | 106/107 不变；`docs/architecture.md` 新增 5 节 |

## 8. 下一阶段建议

进入 Stage 3（Vision Studio，V0.4.0）。前置条件已满足：

1. Studio 直接复用 `ReplaySession` 作为“回放页”和“离线识别”数据源，不需要再写解析逻辑。
2. 画布坐标换算使用 `Frame.viewport` + canonical 坐标；`coordinate_only`/`matched`/`miss` 三种显示
   语义已经有 `Match.status` 支撑。
3. 模板编辑导出走“草稿资源目录 + `assets.yaml` 片段”，不覆盖 `assets/assets.yaml`；阈值试验用
   `tests/fixtures/baseline` 的 32 帧做误检/漏检统计。
4. ADB 预览只需要 `FrameProvider` + `Context.capture_frame()`，帧龄用 `frame_age()` 显示，断线时
   标为不可用，不发送任何输入。
5. 先确认 PySide6 可安装（当前环境未安装），并把 GUI 做成可选依赖，保证 CLI 不受影响。
