# 基线报告（Stage 1 / V0.2.1）

> 生成时间：2026-11-25 01:23（Asia/Shanghai）
> 数据文件：`runtime/diagnostics/baseline.json`（机器可读，本地生成，未纳入 git）
> 复现命令：`python -m bettercoc --config config/mumu.yaml baseline --iterations 100 --adb-iterations 100`
> 结论：现有 66 个测试全部通过；新增 12 个基线测试后共 78 个通过；固定测试集 32 帧 / 107 项标注，
> 106 项符合预期，1 项为已记录的误检缺陷。ADB 截图是识别周期的主要瓶颈（P50 639ms，约占 90%）。
>
> 2026-11-26 增补 `wall_row_label.png`、`wall_entry_15.png`、`wall_entry_16.png` 后资源清单为 33 项、模板 23 个；下文的数量与哈希是增补前的基线记录，识别结论未重新测量。

## 1. 环境与版本

| 项目 | 值 |
| --- | --- |
| git commit | `bd1cab2eeb21a69d29c9eb9b452ff611ec0a35d0`（main） |
| git 工作区 | 有未提交改动：测量前 24 个已修改、5 个未跟踪文件；未回滚、未覆盖任何用户改动 |
| Python | 3.14.7（CPython） |
| 平台 | Windows-10-10.0.19045-SP0，AMD64 |
| OpenCV | 5.1.0 |
| numpy | 2.5.5 |
| PyYAML | 6.0.4 |
| Pillow | 13.0.0 |
| canonical 尺寸 | 1920x1080 |
| 配置 | `config/mumu.yaml`，sha256 `7bb949d0c6226a2c68c204ba0800d883f43dbba958c82646dbf37ddcb45df7de` |
| 资源清单 | `assets/assets.yaml`，30 项，sha256 `f06ccc925b92f29c320aba982c89fcd42fc9eb79062128369efa102570caaf29` |
| 模板 | 20 个 PNG，合并哈希 `927780ed50dbb6ffc75ab7af55b8dc6fdbf3df947d9cd2c6ed7b38336d73b983` |
| 数字模板 | 30 个 PNG，合并哈希 `f26689a47fcae9c6bb6358af5bdeec221b8567fe225946739883a2b8cd3bb4c9` |
| 设备 | MuMu ADB `127.0.0.1:16384`，截图 1920x1080 |

模板合并哈希按文件名 + 文件内容排序后计算，用于检测“模板被替换但清单未变”的情况。资源或模板变更后，
本文的识别结论需要重新跑基线确认。

本次新增文件：`bettercoc/baseline.py`、`tools/build_baseline_fixtures.py`、`tests/fixtures/baseline/`、
`tests/test_baseline.py`、`tests/test_dry_run.py`、`docs/baseline.md`、`docs/stage-1-report.md`。
对既有文件的改动只有三处：`bettercoc/cli.py` 新增 `baseline` 子命令、`bettercoc/resources.py` 在
`_zoom_out_min` 增加 dry-run 短路（见第 6 节）、`README.md` 与版本号。

## 2. 测试与命令结果

### 2.1 现有测试基线

实施前执行 `python -m unittest discover -s tests -v`：

```text
Ran 66 tests in 13.501s
OK
```

无失败、无跳过。新增基线测试后：

```text
Ran 78 tests in 15.866s
OK
```

12 个新测试 = 6 个固定测试集/度量测试（`tests/test_baseline.py`）+ 6 个 dry-run 输入测试
（`tests/test_dry_run.py`）。原有 66 个测试未修改、未删除。

### 2.2 内置 demo

```text
python -m bettercoc demo --cycles 2 --output runtime/baseline-demo
演示状态: success
演示结果: 2 轮，进攻 2 次
模拟器数据: 进攻 2 次，剩余金币 900,000，圣水 800,000
```

demo 输出目录包含 6 张场景图（home / attack_menu / scouting / battle / results / wall_panel）、
8 个模板、配置、日志和最终截图。

### 2.3 doctor

`python -m bettercoc --config config/mumu.yaml doctor` 退出码 0：

```text
[OK  ] 配置文件: config\mumu.yaml
[OK  ] 资源清单: assets\assets.yaml (30 项)
[WARN] 待校准模板 battle_end: assets\templates\battle_end.png
[WARN] 待校准模板 scout_attack: assets\templates\scout_attack.png
[OK  ] 数字模板: assets\digits (30 个)
[OK  ] ADB 设备: 127.0.0.1:16384
[WARN] OCR 不可用；文本识别项不可用，数字资源识别由 assets/digits 提供。
[WARN] 未配置兵种或下兵坐标；自动战斗不依赖手动下兵。
```

两个 WARN 是清单里声明了模板文件但文件不存在：`battle_end`、`scout_attack`。对这两个名字调用
`Vision.find` 会抛 `MissingAssetError`，`find_optional` / `probe` 会跳过，任务主流程不使用它们。
这是一条已知的清单与文件不一致，Stage 2 需要让 `doctor`/`AssetStore` 把它与“待校准”分开报告。

### 2.4 只读命令与设备输入

本次执行涉及设备的命令只有两类：`doctor`（`adb devices` 与 `adb connect`）和基线的
`adb exec-out screencap -p` 采样，都是只读操作，不产生触控、按键、应用重启。未执行
`status --live`（会回主城并 pinch/滑动）、未执行任何任务。

## 3. 固定测试集

### 3.1 来源与生成方式

- 源图：`runtime/mumu` 下的 18 张真实 MuMu 截图（2026-11-24 会话，含断线弹窗、欢迎回家弹窗、
  放弃确认弹窗、城墙批量选择、侦察、战斗、建造列表等）。
- 派生：对其中 6 张做确定性变换（缩放、裁切、高斯模糊、亮度、固定种子噪声），共 32 帧。
- 生成：`python tools/build_baseline_fixtures.py`，输出 `tests/fixtures/baseline/frames/*.webp`
  与 `tests/fixtures/baseline/manifest.json`。生成过程不依赖网络和设备。
- 存储：有损 webp，质量 80，32 帧共 10.96MB，保持 1920x1080 canonical 坐标。`manifest.json`
  记录每帧的源路径、源文件 sha256、变换参数、存储文件 sha256、像素 sha256、标签和说明。
- 取舍：仓库体积与保真度折中。有损编码会让模板得分小幅下降（已用标签验收确认未改变结论），
  标签一律以存储文件为准。

`manifest.json` 同时声明 `assets_manifest: ../../../assets/assets.yaml` 与 `digits_dir`，因此测试集
直接使用正式资源清单与数字模板，不复制一份会漂移的副本。

### 3.2 覆盖类别

| 类别 | 帧数 | 代表帧 |
| --- | --- | --- |
| 主城正常界面 | 14（含墙面板/弹窗叠加） | `home-a`、`home-b`、`home-wall-selected` |
| 联机模式 | 3 | `attack-menu-a`、`attack-menu-side-panel` |
| 我的军队 | 1 | `army-a` |
| 侦察（含自动战斗按钮） | 5 | `scout-a`、`scout-auto-battle` |
| 战斗/放弃确认 | 3 | `battle-a`、`battle-b`、`battle-confirm-dialog` |
| 城墙/建造面板 | 5 | `wall-bulk-a`、`wall-panel-a`、`wall-list-a` |
| 弹窗（欢迎回家/断线/确认） | 10 | `welcome-popup-a/b/c`、`disconnected` |
| 缩放 | 4 | `home-a-scale-1280x720`、`home-a-scale-2560x1440` |
| 裁切 | 3 | `home-a-crop-topleft`、`home-a-crop-center`、`scout-a-crop` |
| 模糊 | 4 | `home-a-blur`、`scout-a-blur`、`wall-bulk-a-blur`、`disconnected-blur` |
| 亮度下降 | 2 | `home-a-dim`、`welcome-popup-a-dim` |
| 固定种子噪声 | 1 | `home-a-noise` |
| 数字区域 | 1 | `scout-a-blur` 的标签说明数字项行为 |

标签共 107 条：52 条期望命中、54 条期望不命中、1 条已知缺陷。标注原则：

- `hit` / `miss`：按画面语义判断“该识别项在此画面是否存在或应当命中”，不是对当前输出的抄写。
- 数字项（`loot_gold` 等）只在数字面板确实可见的帧上标注。它们在 ROI 内见到类数字笔画就返回数值，
  没有存在性校验，因此不在裁切/未知界面上标注，避免把“无意义返回值”固化成期望。
- `known_defect`：语义上不应当命中、但当前确实命中的误检，记录但不判失败（见 3.4）。

### 3.3 验收结果

`bettercoc baseline` 在固定测试集上的结果：

```text
帧 32，检查 107，通过 106，失败 0，已知缺陷 1，已修复 0，错误 0
```

关键正例（期望命中且命中）：`home_attack`、`build_button`、`attack_find_match`、`army_attack`、
`scout_next`、`scout_cancel`、`battle_confirm`、`side_panel_close`、`game_stop`、`wall_entry`、
`wall_add_1`、`wall_add_10`、`wall_cost_gold`、`wall_cost_elixir`、`home_popup_close`（restart1 样式）、
`loot_gold/elixir/dark`。

关键反例（期望不命中且不命中）：主城帧上的 `game_stop`、`auto_battle`、`wall_more`、`army_attack`、
`home_popup_close`；侦察/战斗帧上的 `battle_return_home`、`home_attack`；批量选择帧上的 `wall_confirm`。
这些反例是防止模板误检扩大的护栏。

缩放帧（1280x720、2560x1440）与轻度模糊帧（sigma 1.0）的结论与原始帧一致，说明
`normalize_frame` + Viewport 的坐标往返在 fixture 覆盖范围内成立。

### 3.4 已知问题与能力边界（来自固定测试集）

| 编号 | 现象 | 证据 | 影响 |
| --- | --- | --- | --- |
| B1 | `wall_gold_button` 在断线弹窗（整体变暗）上误检 | 帧 `disconnected`，得分 0.982，位置 (1000,805) | 变暗遮罩下金色按钮模板可能误触发；需要形状/上下文约束 |
| B2 | `auto_battle` 对“自动战斗”另一种按钮样式不命中 | 帧 `scout-auto-battle`，最佳得分 0.581 < 阈值 0.8 | 游戏按钮样式变化后自动战斗会判定为不可用，任务结束本次侦察 |
| B3 | `home_popup_close` 只命中一种弹窗样式 | `welcome-popup-b` 命中；`welcome-popup-a/c` 不命中（X 位置不同、颜色均值 (8.5,7.7,46.7)） | 欢迎回家弹窗可能关不掉，只能靠重试/回主城流程兜底 |
| B4 | 颜色校验对亮度敏感 | `welcome-popup-a-dim`（亮度 70%）`home_popup_close` 不命中；`home-a-dim`（55%）`home_attack` 不命中 | 弹窗遮罩/夜间界面下 point+check 判定会失效 |
| B5 | 模板匹配对模糊敏感（阈值 0.9） | `wall-bulk-a-blur`（sigma 2.0）`wall_add_1` 0.835、`wall_add_10` 0.854 | 压缩/缩放导致的模糊会让高阈值模板失效 |
| B6 | 数字识别项没有存在性校验 | `scout-a-crop` 裁掉数字面板后 `loot_gold` 仍返回 `7` | 状态未到时数字项会返回无意义值；必须由任务状态机先行判断 |
| B7 | 数字识别存在末位误读 | `home-a` 实际 1,697,542，读取 `1697541` | 单帧数字结果不可当作精确余额；影响扣费与阈值判断的精度 |
| B8 | 裁切后 point 的颜色校验区可能落在边缘渐变 | `scout-a-crop` 的 `scout_next` 不命中 | 画面裁切/换分辨率后固定点校验需要重新校准 |

B1 是固定测试集里唯一的 `known_defect`，Stage 2 的识别语义工作要处理“模板命中但上下文不对”的情况。

## 4. 性能测量

### 4.1 方法

`bettercoc baseline` 内每项测量预热（前 3 次），再采样 100 次，报样本数、错误数、P50/P95、均值与极值。
P50/P95 用线性插值分位数。测量代码见 `bettercoc/baseline.py` 的 `measure()` / `time_recognition_pipeline()`
/ `time_adb_capture()`。ADB 项直接计时 `adb exec-out screencap -p` 子进程往返，再用同一份字节数据测解码与归一化。

### 4.2 结果（n=100，错误 0）

| 阶段 | P50 (ms) | P95 (ms) | 说明 |
| --- | --- | --- | --- |
| ADB 截图传输 | 639.231 | 649.939 | `adb exec-out screencap -p`，PNG 载荷 2.34MB（同会话另一次采样 3.53MB，随画面复杂度变化） |
| ADB PNG 解码 | 36.689 | 37.559 | `cv2.imdecode` 1920x1080 |
| ADB 解码+归一化 | 35.778 | 37.341 | 不缩放时归一化只是拷贝 |
| 静态 PNG 解码 | 25.768 | 26.707 | 同尺寸静态图解码，作为解码基准 |
| 归一化（已解码帧） | 0.804 | 1.330 | 1920x1080 到 1920x1080 的拷贝路径 |
| 模板匹配（全屏，单尺度） | 44.649 | 46.150 | `game_stop` 在断线帧上匹配，阈值 0.85 |
| 数字识别（单 ROI） | 1.247 | 1.569 | `home_gold` ROI (1580,20,240x70) |
| 颜色校验（point check） | 0.023 | 0.091 | `home_attack` 的 120x18 区域均值 |
| fixture webp 读取 | 28.732 | 29.409 | 从磁盘读取 1920x1080 有损 webp |

### 4.3 解读

- 单次“截图 + 识别”周期约 640–720ms，其中 ADB 截图占 88%–91%。解码 37ms、模板匹配 45ms 都不是瓶颈。
- 截图为 PNG 全屏编码，单帧 2.3–3.5MB。这是 Stage 5 才评估 scrcpy 的触发条件：基线已表明 ADB 采集是主要瓶颈。
- 数字识别和颜色校验都在毫秒级，一帧内多次数字读取的成本可以忽略；模板匹配量级决定“一帧能跑几个模板”。
  当前 `probe` 对 30 项资产逐项匹配约需 1–2 秒，量级与上表一致。
- ADB 采样期间有一次 639ms、另一次 702ms 的 P50，说明存在会话级波动（模拟器负载、画面复杂度）。
  后续对比实验应在同一会话内交替采样，避免把波动当成优化效果。
- 以上数据全部来自本机实测，未做任何估算填充。真实设备上更高分辨率或不同模拟器需要重测。

## 5. 现有接口审查

### 5.1 调用关系

```text
Context.screen() ──capture.grab()──> normalize_frame ──> Screen(image, viewport, captured_at)
      │                                                   │
      ├── find(target, screen=None) ──> 每次都调用 screen()
      │        └── Vision.find ──> assets.recognition / assets.template ──> template / color / digits / ocr
      ├── wait / try_wait / wait_gone ──> 循环 find()，每次新帧
      ├── click ──> wait + tap_match ──> tap ──> viewport.to_device ──> controller.tap
      └── tap / swipe / back ──> dry_run 分支 / controller

Locator ──> Context.find / wait / click（无独立帧，全部即时采集）

tasks/raid ──> ctx.click / ctx.wait / ctx.try_wait（每步一次新帧）
             └── _read_loot(screen) ──> 同一帧读三个数字
tasks/wall_upgrade ──> ctx.find(WALL_ENTRY)（无 screen，重复采集）
                     └── vision.digits.read(ctx.screen(), roi)（又单独采集一次）
resources ──> ensure_home（每轮 ctx.screen()）→ _read_resources（一帧读三数字）
             → _read_max_values（每次点击后 ctx.screen()）
recovery.ensure_home ──> 每轮 ctx.screen()，同轮所有 find_optional 复用该帧
```

### 5.2 风险清单（未确认的一律标为风险，不作为缺陷）

| 编号 | 风险 | 依据 | 结论 |
| --- | --- | --- | --- |
| R1 | `Screen` 没有帧身份 | `bettercoc/image.py:13` 只有 `image/viewport/source/captured_at`；`normalize_frame` 从不设置 `source` | 无法回答“这个识别结果来自哪一帧”，诊断与回放无法关联 |
| R2 | 不传 `screen` 的 `find` 每次重新采集 | `bettercoc/context.py:87` | 连续多次 `find` 跨越不同帧；同一逻辑判断可能读到不同画面 |
| R3 | 任务里存在重复采集 | `tasks/wall_upgrade.py:262` 单独 `ctx.screen()` 读数字；`:272`、`:278` 两处 `ctx.find(WALL_ENTRY)` 各自采集；`tasks/raid.py:294` 在已有流程里再采集一次 | 单步多帧，增加延迟且放大跨帧不一致；ADB 每次约 640ms |
| R4 | 全局资源状态是模块级可变全局量 | `bettercoc/resources.py:16-25` 的 `GOLD/ELIXIR/...` | 无法区分“观测/估算/缓存/配置兜底”，缺失与 0 不可区分 |
| R5 | 数字项无存在性语义 | `bettercoc/digits.py:110` 只按 ROI 读字符 | 见 B6；任何画面都可能返回值 |
| R6 | `point` 无 `check` 时永远命中 | `bettercoc/vision.py:70`，`_find_point` 直接返回命中 | `build_button` 在任意画面“命中”，不能作为视觉证据；UI 需要区分 coordinate_only |
| R7 | 固定点颜色校验对亮度/样式敏感 | 见 B3/B4，`PointCheck` 只支持多组颜色，不支持多位置 | 同一按钮在不同弹窗样式下位置不同即失效 |
| R8 | 模板误检缺少上下文约束 | 见 B1，`wall_gold_button` 0.982 命中在无关弹窗 | 需要 ROI、相邻元素或状态前提 |
| R9 | 清单声明但文件缺失的模板只有 WARN | `doctor` 把 `battle_end`/`scout_attack` 报成“待校准” | 与“模板未校准”语义混淆；直接 `find` 会抛异常 |
| R10 | 非 16:9 画面被拉伸 | `image.py:36` 固定缩放到 canonical | 非 16:9 下所有坐标与模板都会偏移，当前无告警 |
| R11 | 截图失败只有异常类型，没有诊断事件 | `errors.py` 的 `CaptureError` 等 | 失败现场（帧、阈值、耗时、bbox）不落盘，只能靠日志文本 |
| R12 | 缓存不会过期，但也不造成跨帧复用 | `assets.py:38` 只缓存模板与 spec；Vision 不做结果缓存 | 无“旧图当新帧”问题；模板缓存是期望行为，无需处理 |

审查结论：现阶段不存在“识别结果缓存过期导致旧图被当新帧”的问题（Vision 无结果缓存），
主要问题是帧身份缺失（R1）、单步多帧（R2/R3）和状态语义缺失（R4/R5/R6）。这三类正是 Stage 2
`FrameProvider` / `StateStore` / 结构化诊断要解决的。

## 6. dry-run 审计

### 6.1 方法

用 `StrictController`（任何输入方法都记录并抛错的测试替身）驱动 `Context`，覆盖所有设备输入入口：
`tap`、`swipe`、`back`、`click`/`tap_match`、`resources._zoom_out_min` 的 pinch/scroll、
`recovery.reload_if_stopped` 的点击、`recovery.restart_game` 的 force-stop/start-app。
断言 spy 一次都没有被调用，同时断言 `stats` 计数正常、日志显示 `[dry-run]`。
测试见 `tests/test_dry_run.py`。

### 6.2 发现与修复

`bettercoc/resources.py` 的 `_zoom_out_min` 直接调用 `ctx.controller.pinch/scroll`，绕过了
`Context.tap/swipe` 的 dry_run 分支。也就是说 `--dry-run` 下首次加载资源仍会向设备发送双指缩放事件，
违反“dry-run 只识别和打印点击，不操作设备”。

最小修复：在 `_zoom_out_min` 开头判断 `ctx.dry_run`，只打印跳过日志。修复后
`test_zoom_out_min_skips_device_input_in_dry_run` 通过；不改变正常模式行为。

### 6.3 覆盖与残留

- 已覆盖：按钮点击、滑动、返回键、pinch/scroll、断线重连点击、游戏重启拒绝。
- 未覆盖：`AdbDevice.pinch` 内部拼接的 `sendevent` 序列（真实设备路径，dry-run 下不再可达）；
  `restart_game` 在真实模式下需要设备能力，属于设备侧验证，本次未执行。

## 7. 未验证项

- 真实设备上固定测试集的识别准确率：fixture 来自历史 MuMu 截图，只代表该账号、该 UI、该分辨率。
- OCR 路径耗时与准确率：本机未安装 Tesseract，`NullOcr` 生效。
- 多分辨率真实设备验证：只用缩放/裁切模拟了 1280x720、2560x1440，没有真实设备出图。
- Windows 之外的平台：全部测量在 Windows 10 完成。
- 长时间稳定性：本次没有做 10 分钟级连续预览（属于 Stage 3 验收项）。

## 8. 复现步骤

```powershell
$env:PYTHONPATH = ".deps;.;tests"
python -m unittest discover -s tests -v
python -m bettercoc demo --cycles 2
python -m bettercoc --config config/mumu.yaml doctor
python -m bettercoc --config config/mumu.yaml baseline --iterations 100
python -m bettercoc --config config/mumu.yaml baseline --iterations 100 --adb-iterations 100
```

重新生成固定测试集（需要已有历史截图，截图目录默认 `runtime/mumu`）：

```powershell
python tools/build_baseline_fixtures.py
```

重新生成后必须重跑 `baseline` 并更新本文与 `manifest.json` 中的标签，不允许直接把标签改成当前输出。

## 9. 对 Stage 2 的输入

1. `Frame` 与 `frame_id`：R1/R2/R3 表明需要显式帧对象与“同帧识别”契约；先给 `Context.screen()` 加帧身份，
   再让 `find/match` 结果携带 `frame_id`，不改变现有调用签名。
2. 识别语义：`coordinate_only`（R6）、`matched`、`miss`、`unknown`（R5）需要在结果对象里显式表达，
   UI 与诊断都依赖它。
3. 颜色校验能力：B3/B4/R7 表明单个位置 + 单组颜色不够；至少支持多候选位置或在诊断中显式报告
   “校验点未命中，需重新校准”。
4. 结构化诊断：R11 需要 `event_type/error_code/frame_id/duration_ms` 等字段；失败证据保存截图与参数摘要。
5. 模板清单一致性：R9 需要把“文件缺失”和“未校准”分开报告，避免把异常当成校准提示。
6. 性能预算：ADB 640ms 已占周期 90%，Stage 2/3 的单帧设计必须避免“每次 find 重新截图”；
   离线回放与 Studio 预览必须走静态帧，不能按需截图。
