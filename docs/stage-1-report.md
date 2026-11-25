# Stage 1 报告：基线冻结与性能测量（V0.2.1）

> 完成时间：2026-11-25
> 对应方案：`betterCoC_next_stage_plan.zh-CN.md` 第 3 节
> 判定：**通过**（固定测试集 106/107 符合预期，1 项已登记缺陷；全部单元测试通过）
> 基线数据：`docs/baseline.md`、`runtime/diagnostics/baseline.json`

## 1. 目标

冻结可复现的识别基线：记录环境与资源指纹、跑通现有测试与 demo、建立离线固定测试集与标注、
测量各阶段耗时、审计 dry-run 的设备输入路径、审查现有接口调用关系。不实现 GUI、不重构
`resources.py`、不新增游戏任务。

## 2. 实际修改

新增：

| 文件 | 作用 |
| --- | --- |
| `bettercoc/baseline.py` | 环境/资源指纹采集、`measure()` 分位数统计、固定测试集执行与标签判定、ADB 采样、原子写 JSON、摘要格式化 |
| `tools/build_baseline_fixtures.py` | 从历史 MuMu 截图确定性生成 32 帧 webp fixtures 与 `manifest.json`（含来源 sha256、变换、标签） |
| `tests/fixtures/baseline/manifest.json` | 固定测试集清单与标注（107 条标签） |
| `tests/fixtures/baseline/frames/*.webp` | 32 帧离线基准图，10.96MB |
| `tests/test_baseline.py` | 清单完整性、类别覆盖、标签判定、命中率、`measure` 单元测试（6 个） |
| `tests/test_dry_run.py` | StrictController spy 驱动的 dry-run 设备输入测试（6 个） |
| `docs/baseline.md` | 基线报告 |
| `docs/stage-1-report.md` | 本报告 |

修改：

| 文件 | 修改 | 理由 |
| --- | --- | --- |
| `bettercoc/cli.py` | 新增 `baseline` 子命令（`--fixtures/--output/--iterations/--adb-iterations`） | 基线需要可重复执行入口 |
| `bettercoc/resources.py` | `_zoom_out_min` 增加 `ctx.dry_run` 短路 | dry-run 审计发现 pinch/scroll 绕过 dry-run，属实际缺陷 |
| `bettercoc/__init__.py`、`pyproject.toml` | 版本 0.1.0 → 0.2.1 | 对应方案 Stage 1 建议版本 |
| `README.md` | 增加基线命令与固定测试集说明 | 新增 CLI 入口需要文档 |

未改动用户已有未提交内容：`assets/assets.yaml`、`bettercoc/annotate.py`、`bettercoc/assets.py`、
`bettercoc/recovery.py`、`bettercoc/spec.py`、`bettercoc/tasks/*`、`bettercoc/vision.py`、`docs/*.md`
等其他修改均保留原状。`cli.py` 与 `resources.py` 本身已在用户未提交改动列表中，本次只做了上述追加。

## 3. 命令与结果

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests -v` | 66 tests, OK（实施前基线） |
| 同上（实施后） | 78 tests, OK, 15.9s |
| `python -m bettercoc demo --cycles 2 --output runtime/baseline-demo` | success，2 轮，进攻 2 次 |
| `python -m bettercoc --config config/mumu.yaml doctor` | 退出码 0，3 个 OK、4 个 WARN（含 2 个待校准模板、OCR 不可用） |
| `python -m bettercoc --config config/mumu.yaml baseline --iterations 100 --adb-iterations 100` | 32 帧 / 107 项：106 通过、0 失败、1 已知缺陷；9 组耗时各 100 样本、0 错误 |
| `python tools/build_baseline_fixtures.py` | 生成 32 帧，10.96MB |

未执行：`status --live`、任何任务运行、任何会导航界面的命令。设备侧只执行了 `adb devices`/`connect`
和只读 `screencap` 采样。

## 4. 性能统计

n=100，P50/P95（ms），错误 0：

| 阶段 | P50 | P95 |
| --- | --- | --- |
| ADB 截图传输 | 639.2 | 649.9 |
| ADB PNG 解码 | 36.7 | 37.6 |
| ADB 解码+归一化 | 35.8 | 37.3 |
| 静态 PNG 解码 | 25.8 | 26.7 |
| 归一化 | 0.8 | 1.3 |
| 模板匹配（全屏单尺度） | 44.6 | 46.2 |
| 数字识别（单 ROI） | 1.2 | 1.6 |
| 颜色校验 | 0.023 | 0.09 |
| webp 基准帧读取 | 28.7 | 29.4 |

结论：ADB 截图占单帧周期约 90%，单帧 PNG 载荷 2.3–3.5MB；识别侧（模板 45ms、数字 1.2ms、颜色 0.02ms）
不是瓶颈。该结论是 Stage 5 评估 scrcpy 的触发条件，也是 Stage 2 “禁止每次 find 重新截图”的依据。

## 5. 未完成项

- 真实多分辨率设备验证（只有缩放/裁切的模拟帧）。
- OCR 路径的耗时与准确率（本机无 Tesseract）。
- 长时间稳定性测量（属 Stage 3 验收）。
- 固定测试集只覆盖一个账号、一种语言、1920x1080 UI。

## 6. 已知风险

1. 固定测试集会随资源清单漂移：`manifest.json` 指向 `assets/assets.yaml`，模板更换后标签可能失效。
   已记录清单与模板合并哈希；变更后必须重跑基线。
2. 有损 webp 存储：得分与原始 PNG 有差异，标签以存储文件为准；已通过命中率测试确认结论未变。
3. 1 项已登记缺陷：`wall_gold_button` 在变暗的断线弹窗上误检（0.982）。Stage 2 需引入上下文约束或
   更弱的颜色/形状联合判定。
4. 颜色校验（point+check）对亮度敏感：亮度 70% 时 `home_popup_close` 失效，55% 时 `home_attack` 失效。
   当前恢复流程能处理部分场景，但没有显式诊断。
5. `resources.py` 的 dry-run 短路是行为修复，若用户依赖 dry-run 下也执行 pinch 将不再发生（符合 dry-run 语义）。
6. 基线测试无法发现“真实设备画面与 fixture 分布不同”的问题，例如新 UI、新弹窗。

## 7. 验收判定

| 方案验收项 | 判定 | 证据 |
| --- | --- | --- |
| 记录 commit、Python/依赖、配置与资源版本 | 通过 | `docs/baseline.md` 第 1 节，`baseline.json.environment` |
| 执行 README 测试命令及 demo，记录真实通过/失败/跳过 | 通过 | 66 → 78 tests OK，无跳过；demo success |
| 审查 Context/Vision/Locator/resources/recovery 调用关系 | 通过 | `docs/baseline.md` 第 5 节 R1–R12 |
| 建立至少 30 张标注集，覆盖正常/弹窗/未知/模糊数字/相似图标/裁剪/缩放 | 通过 | 32 帧、107 标签、类别覆盖测试 |
| 分段耗时，每组至少 100 次，报告样本/P50/P95/错误/环境 | 通过 | 9 组 × 100 样本，错误 0 |
| 检查 dry-run 所有设备输入路径并用 mock spy 确认无真实输入 | 通过（含 1 处修复） | `tests/test_dry_run.py`，`_zoom_out_min` 修复 |
| 输出 `docs/baseline.md`、`runtime/diagnostics/baseline.json`、固定测试集与标注清单 | 通过 | 均已生成 |
| 现有测试不新增失败 | 通过 | 78/78 |
| 性能数值来自实测 | 通过 | 全部由 `measure()` 采样，含环境与样本数 |

## 8. 下一阶段建议

按方案进入 Stage 2（V0.3.0），但要按本次测量与审查收窄范围：

1. 先做 `Frame` 与帧身份（R1/R2/R3），提供 `Context.screen()` 兼容的帧对象，识别结果携带 `frame_id`；
   用 fixture 建立“同帧/过期帧”单元测试。
2. 再做识别语义：区分 `coordinate_only`/`matched`/`miss`/`unknown`，解决 R5/R6；数字项必须带存在性前提或
   显式 unknown。
3. 诊断事件与录制回放优先于 StateStore：录制回放能以 fixture 离线复现 B1–B8，是修复这些缺陷的验证手段。
4. `StateStore` 只做观测/诊断状态，不替换 `resources.py` 的全局变量；先解决“缺失≠0、配置上限≠实测上限”。
5. 模板清单一致性（R9）与 point 多候选（B3/B4）作为小修一并处理。
6. 每次改动后跑 `scripts\test.ps1` 与 `bettercoc baseline`，标签变化必须在报告中说明原因。
