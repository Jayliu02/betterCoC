# 架构设计

## 总览

```text
┌──────────────┐   BGR frame    ┌──────────────────┐
│ Capture      │───────────────>│ normalize_frame  │
│ ADB/Folder   │                │ 1920x1080 Screen │
│ Static       │                │ Viewport         │
└──────────────┘                └────────┬─────────┘
                                         │
                                ┌────────▼─────────┐
                                │ Vision           │
                                │ Template/Color/  │
                                │ Digits/OCR       │
                                └────────┬─────────┘
                                         │ Match
                                ┌────────▼─────────┐
                                │ Context          │
                                │ wait/click/tap   │
                                │ stop/stats/dry   │
                                └────────┬─────────┘
                                         │
                                ┌────────▼─────────┐
                                │ StateMachine     │
                                │ raid             │
                                └────────┬─────────┘
                                         │ device coords
                                ┌────────▼─────────┐
                                │ Controller       │
                                │ ADB input        │
                                └──────────────────┘
```

## 截图与坐标

`Capture` 协议只有 `grab()` 和 `close()`。实现：

- `AdbCapture`：`adb exec-out screencap -p`
- `FolderCapture`：按文件名顺序循环读取图片
- `StaticCapture`：每次都返回同一张图

`normalize_frame` 把画面缩放到 `vision.canonical_size`，并生成 `Viewport`：

```python
Viewport(device_width=1280, device_height=720, canonical_width=1920, canonical_height=1080)
```

所有识别配置、模板裁剪、任务坐标都使用 canonical 坐标。`Context.tap` 在发送前调用 `Viewport.to_device`：

```text
device_x = canonical_x * device_width / 1920
device_y = canonical_y * device_height / 1080
```

这样做的好处是换模拟器分辨率时不用改模板和坐标。4:3 画面会被拉伸，建议固定 16:9。

## 识别对象

`Recognition` 是 frozen dataclass，描述“要找什么”：

| 字段 | 适用类型 | 说明 |
| --- | --- | --- |
| `kind` | 全部 | `template`、`ocr`、`color`、`digits`、`point` |
| `roi` | 全部 | 搜索区域，`None` 表示全屏 |
| `threshold` | 模板 | 匹配阈值 |
| `grayscale` | 模板 | 灰度匹配，默认 True |
| `method` | 模板 | `ccoeff_normed`、`ccorr_normed`、`sqdiff_normed` |
| `scales` | 模板 | 多尺度系数，默认 `[1.0]` |
| `file` | 模板 | 相对 `template_root` 的文件 |
| `point` | 固定坐标 | 点击位置 `[x, y]` |
| `check` | 固定坐标 | 可选的平均颜色校验 `roi` / `color`(BGR) / `tolerance` |
| `use_alpha` | 模板 | 使用 PNG Alpha 作为遮罩 |
| `mask_color` | 模板 | 忽略指定颜色 |
| `text_any` / `text_all` / `regex` | OCR | 文本过滤 |
| `lang` / `psm` / `upscale` / `binarize` / `invert` | OCR | 识别参数 |
| `space` / `lower` / `upper` / `min_area` / `min_ratio` | 颜色 | 颜色范围与面积过滤 |

`Recognition` 不持有图像。`Vision` 从 `AssetStore` 取模板并缓存。

### 固定坐标

`Kind.POINT` 直接返回 `point` 坐标上的 `Match`，`Context.tap_match()` 点击该点，不需要模板文件。`check` 存在时，先取 `roi` 的平均 BGR，与 `check.color` 比较最大通道差值，超过 `tolerance` 视为未命中。适合按钮位置固定、但需要在动作前确认画面的场景；比模板匹配快，也不受图标换图影响。

### 模板匹配

`find_template` 的流程：

1. 按 `roi` 裁剪画面，并转换灰度或保留三通道
2. 对每个 `scale` 缩放模板，跳过大于搜索区域的尺寸
3. 调用 `cv2.matchTemplate`
4. `sqdiff` 模式把分数取反，统一成“越大越好”
5. 按阈值过滤，单目标直接取最大值，多目标做 NMS
6. 把结果坐标加回 ROI 偏移

掩码处理：

- 4 通道 PNG 且 `use_alpha`：Alpha > 8 的像素参与匹配
- `mask_color`：与指定 BGR 颜色距离小于容差的像素被排除
- OpenCV 的 `TM_CCOEFF_NORMED` 不支持掩码，遇到掩码会自动换成 `TM_CCORR_NORMED`

多尺度会放大计算量。真实任务优先固定分辨率，把 `scales` 保持为 `[1.0]`。

### 颜色识别

颜色识别把 ROI 转到 HSV 或 BGR，`inRange` 后做开闭运算，找外轮廓，按面积和占比过滤。返回最大色块的包围盒。适合：

- 升级按钮是否变绿
- 资源条是否满
- 按钮是否可点

颜色识别的 ROI 可以由任务动态传入，例如按模板匹配框裁剪按钮区域做颜色确认。

### OCR

`OcrBackend` 协议只有 `available()` 和 `read()`。默认实现 `TesseractOcr`：

- 灰度、可选放大、可选二值化/反色
- `image_to_data` 按 `block/par/line` 合并成行
- 返回 `Match`，`text` 是行文本，`score` 是平均置信度

`filter_text` 支持全部包含、任一包含、正则。`parse_number` 支持 `1,234`、`1.2M`、`350K`、`35万`、`2亿`。

没有安装 Tesseract 时使用 `NullOcr`。文本识别项会抛出 `OcrUnavailable`；金币/圣水/暗黑由数字模板识别，不依赖 OCR。

## 资源清单

`assets/assets.yaml`：

```yaml
version: 1
template_root: templates
defaults:
  threshold: 0.86
  grayscale: true
  method: ccoeff_normed
assets:
  home_attack:
    type: point
    point: [110, 935]
    check:
      roi: [60, 1027, 120, 18]
      color: [41, 157, 207]
      tolerance: 25
  wall_entry:
    file: wall_entry.png
    threshold: 0.8
  loot_gold:
    type: digits
    roi: [70, 125, 250, 50]
```

`defaults` 会合并进每个模板项。条目可以写成字符串简写：

```yaml
assets:
  home_attack: home_attack.png
```

`AssetStore` 负责：

- 解析类型与字段
- 解析相对路径
- 懒加载模板并缓存
- 检查缺失文件与格式错误

`doctor` 区分两类问题：

- `FAIL`：配置损坏、ROI 小于模板、参数非法
- `WARN`：模板未校准、ADB 未连接、OCR 未安装、坐标未配置

## 运行时 Context

`Context` 是任务看到的外观：

| 方法 | 行为 |
| --- | --- |
| `screen()` | 截图、归一化、更新 Viewport、统计 |
| `find()` | 单次识别，可复用同一帧 |
| `find_all()` | 多目标识别 |
| `find_optional()` | 清单里没有该项时返回 `None` |
| `wait()` | 循环截图识别，超时抛 `RecognitionTimeout` |
| `try_wait()` | 超时返回 `None` |
| `wait_gone()` | 等待元素消失 |
| `click()` | 等待并点击命中中心 |
| `tap()` | canonical 坐标 → 设备坐标，抖动，dry-run，延迟 |
| `back()` | keyevent 4 |
| `sleep()` | 可被停止信号打断 |
| `request_stop()` | 设置停止事件 |

`wait` 的超时判断使用注入的 `clock`，测试可以替换。真实运行使用 `time.monotonic`。

`tap` 的随机抖动和延迟在 `control` 配置里：

```yaml
control:
  tap_jitter: 2
  delay_ms: [120, 280]
```

`dry_run` 打开时只打印坐标，不调用 Controller。

## 状态机

`StateMachine` 只做三件事：

- 按名称调用状态处理器
- 处理器返回下一个状态，返回 `None` 结束
- 异常时转到 `on_error` 状态，`StopRequested` 直接向上抛

```python
machine.add("prepare", self._prepare, on_error="recover")
machine.add("raid", self._raid, on_error="recover")
machine.add("recover", self._recover)
machine.add("finish", self._finish)
machine.run("prepare")
```

每次转移记录 `source`、`target`、`elapsed`。任务结果里带完整转移列表，`--trace` 会打印。

状态处理器共享 `Memory`：

```python
@dataclass
class Memory:
    cycles: int
    raids: int
    errors: int
    fatal: bool
```

`recover` 会尝试回主城。恢复次数超过 `max_errors` 后标记 fatal，任务以 `failed` 结束。

## 错误处理

| 异常 | 场景 | 处理 |
| --- | --- | --- |
| `RecognitionTimeout` | 等待元素超时 | 状态机转 `recover` |
| `MissingAssetError` | 清单缺项或模板文件缺失 | 直接失败，提示校准 |
| `DeviceError` | ADB 不可用 | CLI 打印错误 |
| `CaptureError` | 截图解码失败 | CLI 打印错误 |
| `OcrUnavailable` | OCR 未安装 | 仅在 OCR 流程抛出 |
| `StopRequested` | Ctrl+C 或超时停止 | 任务返回 `stopped` |

任务异常时会保存 `runtime/screenshots/*-raid-error.png`。

## 帧与帧身份

`bettercoc/frame.py` 在 `Screen` 之上增加帧身份，`Context.screen()` 的返回类型不变：

```text
Capture.grab() ──> normalize_frame ──> Screen(image, viewport)
                                            │
                              FrameProvider.capture()
                                            ▼
Frame(frame_id, source_id, sequence, raw_size, viewport,
      captured_at=单调时钟, captured_wall=墙钟, image=只读视图)
                                            │
                              Frame.to_screen() ──> Screen.frame_id
```

| 接口 | 行为 |
| --- | --- |
| `Context.screen()` | 采集新帧并返回 `Screen`，`screen.frame_id` 标识输入帧 |
| `Context.capture_frame()` | 采集并返回 `Frame`，同时更新 `last_frame`、`last_screen`、`viewport` |
| `Context.current_frame()` | 返回最近一帧，不重新采集；没有帧时采集一次 |
| `Context.refresh_frame()` | 显式重新采集 |
| `Context.frame_age()` | 最近一帧的年龄（秒） |
| `Context.find_in(frame, ...)` | 在指定帧上识别；帧超过 `stale_after` 抛 `FrameStaleError` |
| `Frame.is_stale(max_age, now)` | 超过 `stale_after`（默认 2 秒，配置 `runtime.frame_stale_after`）视为过期 |

`Match` 新增 `frame_id`、`threshold`、`status`：识别结果携带输入帧身份，同一帧上的多次识别共享
同一个 `frame_id`。`Vision.find_all` 从 `screen.frame_id` 回填，模板命中同时回填阈值。

同一诊断批次内共享同一 `Frame`，图像是只读视图（`Frame.copy_image()` 需要可写副本）。
过期帧不会被静默当作新帧：`find_in` / `find_all_in` 显式拒绝，必须调用 `refresh_frame()`。

## 识别语义

`Match.status` 区分四种语义：

| 状态 | 含义 |
| --- | --- |
| `matched` | 有视觉证据：模板 / 颜色 / 数字 / OCR 命中，或 point 的颜色校验通过 |
| `miss` | 未命中（由 `find` 返回 `None` 表达，事件里记为 `miss`） |
| `coordinate_only` | `type: point` 没有 `check`，只代表固定坐标，不能当作目标存在证据 |
| `unknown` | 识别无法执行或状态未知（如数字区域为空、OCR 不可用） |

`coordinate_only` 用于 CLI、Studio 和诊断事件，避免把“点了固定坐标”展示成“识别成功”。

## 诊断事件

`bettercoc/events.py` 定义统一事件字段：

```text
run_id, event_type, timestamp, monotonic, frame_id, recognition_id,
name, status, score, threshold, bbox, duration_ms, error_code, message, detail
```

- `EventType`：`session`、`capture`、`recognition`、`tap`、`state`、`error`、`task`。
- `ErrorCode`：设备不可用、截图失败、资源缺失、OCR 不可用、识别缺失、状态未知、超时、取消、
  配置错误、帧过期、存储失败、任务错误、内部错误。
- `EventLog` 是有界内存日志（默认 2000 条）+ 可选 JSONL 落盘，线程安全，记录丢弃数量。
- `classify_error(exc)` 把现有异常映射成 `ErrorCode`，不改变任务的恢复策略。

## 录制与离线回放

`bettercoc/recorder.py` 只做只读诊断录制：

```text
sessions/<run_id>/
  manifest.json     schema 版本、时间、canonical、来源、资源指纹、配置快照、帧元数据
  frames/*.png      保存的 canonical 帧（无损 PNG）
  events.jsonl      识别与环境事件
  report.json       帧数、事件数、丢弃/截断、错误码统计、耗时
```

限制：`RecorderLimits(max_frames, max_events, max_frame_bytes)`，超出后跳过并标记 `truncated`，
不静默丢数据。资源指纹包含资源清单与全部模板的 sha256，回放时对比并给出 `assets_changed` 警告。

`bettercoc/replay.py` 从会话目录恢复 `Frame`（不创建任何 Capture，也不连接 ADB），逐帧重跑识别，
与录制事件逐项对比状态、分数与 bbox。分数容差固定为 `1e-3`（事件里的分数保留 4 位小数）。

## 状态存储

`bettercoc/state_store.py` 是与游戏任务解耦的观测/诊断状态模型：

| 字段 | 取值 |
| --- | --- |
| `value` | 可空；缺失不等于 0 |
| `source` | `observed` / `estimated` / `cached` / `configured` |
| `status` | `valid` / `stale` / `unknown` |
| `observed_at` | 观测墙钟时间，用于计算新鲜度 |
| `frame_id` | 观测来自哪一帧 |
| `reason` | 为什么缺失、过期或使用配置兜底 |
| `schema_version` | 当前为 1 |

`StateStore` 支持历史 `resource-state.json` 兼容读取（映射为 `cached`、无观测时间），新格式单独
落盘，不覆盖旧文件。写入使用临时文件 + 原子替换，失败时抛 `StateError` 且旧文件保持不变。
`capacity_check` 把“余额超过已知上限”标为 `over_capacity` 并说明可能是上限未刷新或识别误差，
不直接判为识别错误。

## Vision Studio

`bettercoc/studio/` 是可选 GUI（PySide6），只读接入现有能力：

```text
StudioSource ──> FixtureSource（固定测试集）
             ├─> SessionSource（录制会话，复用 ReplaySession）
             └─> LiveSource（FrameProvider + 只读截图）

ImageCanvas ── 等比缩放/留白 ──> 画布像素 <-> canonical 坐标（studio/geometry.py）
RecognitionRow ──> matched / coordinate_only / miss / unknown + 得分/阈值/区域/耗时
TemplateEditor ── 框选 ──> evaluate_draft（误检/漏检） ──> export_draft（草稿，不覆盖正式资源）
BackgroundRunner ── 单线程 QThreadPool + 有界待处理队列，主线程只渲染
```

边界：Studio 不引用 `Controller`，源码扫描测试禁止设备输入关键字；设备预览只做 `screencap`，
采集在 worker 线程；关闭窗口时 `shutdown()` 等待线程结束，并关闭数据源与截图后端。

## 扩展点

### 新截图后端

实现 `Capture` 协议，并在 `create_capture` 注册。窗口截图可以用 `mss` 或 Win32 BitBlt，注意模拟器 DirectX 画面可能抓黑。

### 新识别类型

在 `Recognition` 增加字段，在 `Vision.find_all` 分派，在 `AssetStore` 增加解析。颜色和 OCR 已经按这个方式接入。

### 新任务

继承 `Task`，实现 `run(ctx)`，注册到 `tasks/__init__.py` 的 `TASKS`。

```python
class MyTask(Task):
    name = "my_task"

    def run(self, ctx: Context) -> TaskResult:
        ctx.click("home_attack")
        return TaskResult(task=self.name, status="success", reason="done", counters=ctx.stats.to_dict())
```

### 组合任务

`farm_wall` 不复制进攻和升级逻辑，而是按条件调用两个子任务：

```python
if full:
    result = WallUpgradeTask(max_upgrades=0, batch_size=0).run(ctx)
else:
    result = RaidTask(max_cycles=1).run(ctx)
```

`WallUpgradeTask` 以建造栏读到的可升级数量为准，读到 0 时返回 `wall_complete=1`。`farm_wall` 汇总进攻次数、升级数量、金币/圣水消耗，并根据这个观测结果决定是否结束，不维护固定总城墙数。两个子任务都可以单独运行。

### 定位器用法

`Context.locate` 提供 BetterGI 风格的链式调用：

```python
ctx.locate("home_attack").with_timeout(5).click()
ctx.locate("auto_battle").try_wait_for(2)
ctx.locate("dialog_ok").with_roi(Rect(700, 500, 500, 300)).click_if_exists()
```

`Locator` 内部复用 `Context` 的等待与点击，不改变过程式 API。任务仍然可以直接调用 `ctx.wait`。

## 测试策略

- 几何：矩形解析、裁剪、IoU、Viewport 换算
- 识别：精确匹配、ROI、多尺度、掩码、NMS、颜色、数字解析、文本过滤
- 资源清单：类型解析、缺失文件、非法阈值
- 状态机：线性转移、异常恢复、最大步数
- 集成：内置模拟器完整跑 2 轮进攻，断言进攻 2 次、回主城

模拟器测试不依赖 Android 设备，适合 CI。
