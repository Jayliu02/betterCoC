# 城墙升级 wall_upgrade

## 状态

已实现并在 MuMu 中文版 1920x1080 实测通过：单段、9 段批量、两次连续升级均成功。批量界面用“移除城墙”文字模板确认，确认弹窗用 `wall_confirm` 模板定位；按钮仍按 1920x1080 固定坐标，批量上限 9 段以保持 X1 布局。

任务名：`wall_upgrade`，实现：[bettercoc/tasks/wall_upgrade.py](../bettercoc/tasks/wall_upgrade.py)。

运行：

```powershell
bettercoc --config config/mumu.yaml run --task wall_upgrade --trace
```

## 目标

不预设城墙总数，也不假设所有城墙等级相同。以“建造”列表里城墙行显示的可升级数量为准：

- 显示 `xN` 且 `N > 0`：还有 N 段可以升级，继续升
- 所有城墙行都显示 `x0`，或列表里没有城墙入口：当前大本营等级下已经没有可升级城墙，结束

城墙行显示的是当前可升级的那一组城墙（例如 `城墙（12级）`）的数量。某一等级全部升完后，下一次进入会读到下一等级的数量，因此每次升级后都重新读一次，不靠减法推算。

建造列表可能同时出现多个城墙行（不同等级）。任务扫描当前屏幕上的所有城墙行，优先选择数量大于 0 的行；当前行为 0 时继续向下找，直到所有行都为 0 或没有城墙入口。示例：

```text
城墙 x0
城墙 x125
```

会先升级 `x125` 这一组，再回头处理其他行。

## 流程

```text
prepare ──> open ──> select ──> upgrade ──> decide
               ▲                              │
               │                              ├── 还有资源：reopen ──> select
               │                              └── 资源不足/达到限制：finish
任意状态异常 -> recover -> prepare
```

### prepare

- 回主城，关闭侧边栏和欢迎弹窗
- 读取右上角金币、圣水、暗黑
- 写入 `runtime/resource-state.json`
- 记住任务开始时的资源

### open

1. 点击主城右下角“建造”
2. 在“建筑和英雄”列表里找到所有“城墙”行
3. 逐个读取城墙行右侧的可升级数量
4. 优先选择数量大于 0 的行；全部为 0 或没有城墙入口时结束
5. 点击该行，再点固定位置 `(925,753)` 的“升级更多”
6. 用 `wall_batch_remove`（“移除城墙”）确认批量界面已经打开；`wall_add_1` / `wall_add_10` 作为备用确认

找不到城墙入口时，用 `side_panel_close` 判断“建造”面板是否已经打开：

- 面板已打开、列表里没有城墙：按“没有可升级城墙”结束
- 面板没有打开：抛错进入 recover

滑动策略：先看当前屏幕；没有可升级行时先滑到顶部，再向下逐屏扫描，避免面板记住上次滚动位置。

### select

1. 在 X1 状态读取每段升级成本（金币/圣水）
2. 两种货币的读数不一致时取识别分更高的一项；只有一种读到时两者共用该值，避免把灰掉的成本读成兜底价
3. 计算当前资源可负担段数
4. 批次取以下值的最小值：
   - 读到的可升级数量（读不到时用 `unknown_batch_size`）
   - 当前资源可负担段数
   - `batch_size`
   - `max_batch`（默认 9，保持 X1 按钮布局）
   - 剩余 `max_upgrades`（`0` 表示不限制）
   - `MAX_BATCH`（30）
5. 用固定位置“添加城墙 +10 / +1”选到目标段数
6. `prefer_currency: auto`：金币够就用金币，否则用圣水；指定的货币不够时自动换另一种

### upgrade

1. 点击固定位置的金币或圣水升级按钮
2. 用 `wall_confirm` 等确认弹窗出现；4 秒内没出现就抛错进入 recover，不扣资源
3. 点击“确定”
4. 扣减内存中的资源、累计升级段数
5. 本批次结束后把已读数量标记为过期，不再用减法推算

### decide

- 达到 `max_upgrades`（非 0 时）结束
- 两种货币都不足单段成本结束
- 否则 `reopen`：重新读城墙数量，再进入批量界面

完成条件只认新的观测结果：建造列表里识别到的城墙行全部读数为 0，或数量未知时批量界面连续两次打不开（`complete_on_no_batch`）。找不到任何城墙行会报错进入 recover，不会静默判定为完成，避免模板不匹配时误报“无升级项”。

## 识别项

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `build_button` | 固定位置 | 主城右下角“建造” |
| `wall_row_label` | 模板 | 城墙行固定文字“城墙 x”，不随城墙等级变化，优先用它找行 |
| `wall_entry_15` / `wall_entry_16` | 模板 | 两种城墙等级的图标，文字模板失效时备用 |
| `wall_entry` | 模板 | 旧版城墙图标，最后备用 |
| `wall_add_1` / `wall_add_10` | 模板 | 备用确认批量升级界面已打开 |
| `wall_batch_remove` | 模板 | “移除城墙”文字，确认批量界面已打开 |
| `wall_confirm` | 模板 | 升级确认弹窗“确定” |
| `side_panel_close` | 固定位置 | 确认“建造”面板已打开 |
| `home_gold` / `home_elixir` / `home_dark` | 数字 | 主城资源 |
| `wall_cost_gold` / `wall_cost_elixir` | 数字 | 每段城墙成本 |

城墙图标会随城墙等级改变外观，因此扫描时同时尝试 `wall_row_label`、`wall_entry_15`、`wall_entry_16` 和旧 `wall_entry`，按行 y 去重。文字模板能同时命中多个等级的行；某一等级升完、数量变成 0 后，扫描会继续选下一行，直到所有识别到的城墙行都为 0。换分辨率或城墙等级后，需要重新裁剪对应图标模板。

`wall_more`、`wall_confirm` 等旧模板保留，批量界面按钮仍用固定位置。

## 按钮固定位置

批量界面初始为 X1，任务从这个状态加数量：

| 步骤 | 坐标 |
| --- | --- |
| 升级更多 | 925,753 |
| 添加城墙 +1 | 908,760 |
| 添加城墙 +10 | 710,755 |
| 金币升级 | 487,930 |
| 圣水升级 | 707,930 |
| 确定 | 1168,707 |

坐标从 `task.wall_upgrade` 读取，并写入 `runtime/wall-buttons.json`。换分辨率或换 UI 后需要重新确认。

## 城墙数量与等级

“建造”里的城墙行包含等级徽标和可升级数量。示例：

```text
城墙 x299
```

表示当前这一组还有 299 段可以升级。升级完这一组后，下一轮会读到下一组，例如：

```text
城墙 x1
```

任务不维护 `总城墙数 - 已完成数` 这样的推算，因此：

- 不同大本营城墙总数不同：不需要改配置
- 同一大本营存在多个城墙等级：逐组升级，直到读到 0
- 升级大本营后城墙重新出现可升级项：下次运行会重新读取并继续

数量读取范围默认限制在 `0..max_walls`（默认 500）。超出范围视为识别失败，按“数量未知”处理，不会拿错误读数结束或超选。

## 资源策略

用户要求：金币和圣水都可以，只要存量足够。

实现：

- 在批量选择 X1 状态读取单段成本
- 总成本 = 单段成本 × 段数
- `prefer_currency: auto`：金币够就用金币，否则用圣水
- 指定的货币不够时自动换另一种
- 两种货币都不够时，按可负担段数缩减批次
- 每批确认成功后扣减内存资源，下一轮回主城重新读取真实资源

### 数量未知时

数字识别读不到时不会当成 0：

- 批次限制到 `unknown_batch_size`（默认 10），避免一次选中不存在的城墙
- 继续尝试升级
- 下一轮重新读；只有明确读到 0、找不到城墙入口，或批量界面连续两次打不开时才结束

`complete_on_no_batch`（默认 `true`）用于读不到数量、但批量界面连续打不开的情况：这也说明当前没有可升级城墙，按完成处理。数量能读到时批量界面打不开仍按错误处理，进入 recover，不会误判完成。

## 状态文件

```json
{
  "updated_at": "2026-11-24 01:55:49",
  "gold": 4600000,
  "elixir": 3740620,
  "dark": 207500,
  "gold_before": 4600000,
  "elixir_before": 9740620,
  "gold_spent": 0,
  "elixir_spent": 6000000,
  "wall_upgrades": 10,
  "wall_upgraded": 10,
  "wall_remaining": 0,
  "wall_complete": true,
  "wall_cost_gold": 600000,
  "wall_cost_elixir": 600000
}
```

| 字段 | 说明 |
| --- | --- |
| `wall_remaining` | 最近一次读到的可升级数量；`read` 失败时不写入 |
| `wall_upgraded` | 本次任务升级数量 |
| `wall_complete` | 是否已经读到“没有可升级城墙” |
| `wall_cost_gold` / `wall_cost_elixir` | 最近一次读到的单段成本 |

## 配置

```yaml
task:
  wall_upgrade:
    max_upgrades: 0
    batch_size: 10
    max_batch: 9
    unknown_batch_size: 10
    max_walls: 500
    max_cycles: 0
    max_runtime_min: 15
    max_errors: 2
    cost_per_wall: 600000
    prefer_currency: auto
    scroll_times: 10
    scroll_duration_ms: 400
    settle_ms: 1500
    remaining_offset: [115, -19, 120, 50]
    icon_remaining_offset: [115, -14, 120, 45]
    complete_on_no_batch: true
    gold_button: [487, 930]
    elixir_button: [707, 930]
    more_point: [925, 753]
    add_wall_point: [908, 760]
    add_ten_point: [710, 755]
    confirm_point: [1168, 707]
    state_file: runtime/resource-state.json
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `max_upgrades` | 0 | 本次最多升级几段；0 表示只受资源和数量限制 |
| `batch_size` | 10 | 每批选择几段；0 表示按可升级数量和资源计算 |
| `max_batch` | 9 | 单批上限；选到 10 段时游戏会切换成更宽的按钮布局，固定坐标失效 |
| `unknown_batch_size` | 10 | 读不到可升级数量时，每批最多选几段 |
| `max_walls` | 500 | 可升级数量的合理上限，超出视为识别失败 |
| `max_cycles` | 0 | 本次最多升级几批；0 表示不限制，由资源决定 |
| `max_runtime_min` | 15 | 单次任务运行时长上限，0 表示不限制 |
| `max_errors` | 2 | 连续 recover 次数上限 |
| `cost_per_wall` | 600000 | 读不到成本时的兜底单价 |
| `prefer_currency` | auto | `auto` / `gold` / `elixir` |
| `scroll_times` | 10 | 建造栏滑动最大次数 |
| `settle_ms` | 1500 | 确认后的等待 |
| `remaining_offset` | [115,-19,120,50] | 旧图标锚点下读取数量的 ROI |
| `icon_remaining_offset` | [115,-14,120,45] | `wall_entry_15` / `wall_entry_16` 图标锚点下读取数量的 ROI |
| `complete_on_no_batch` | true | 数量未知且批量界面连续打不开时按完成处理 |
| `gold_button` | [487,930] | 金币升级按钮坐标 |
| `elixir_button` | [707,930] | 圣水升级按钮坐标 |
| `more_point` | [925,753] | “升级更多”坐标 |
| `add_wall_point` | [908,760] | “添加城墙 +1”坐标 |
| `add_ten_point` | [710,755] | “添加城墙 +10”坐标 |
| `confirm_point` | [1168,707] | 确认弹窗“确定”坐标；有 `wall_confirm` 时优先模板定位 |

## 实测

以下是旧版固定批量流程的 MuMu 实测记录，用于确认按钮坐标和成本识别；新循环的完成判断还需要真机验证。

2 段，金币：

```text
选择 2 段城墙，成本 金币 1200000 / 圣水 1200000，使用 金币
城墙升级完成 2 段，总计 2 段
金币 5800000 -> 4600000
```

10 段，金币不足切圣水：

```text
选择 10 段城墙，成本 金币 6000000 / 圣水 6000000，使用 圣水
城墙升级完成 10 段，总计 10 段
金币 4600000 -> 4600000
圣水 9740620 -> 3740620
```

单次 10 段耗时约 38 秒，主要时间在建造栏滑动和界面动画。

## 常见问题

### 建造栏找不到城墙

- 任务会先把列表滑到顶部，再向下找
- 优先确认 `wall_row_label`（“城墙 x”文字）模板来自当前分辨率和语言；不同窗口大小会改变文字渲染
- 新加或替换模板后需要重启 `bettercoc` 进程，资源清单和模板在启动时加载；只重进游戏不会重新加载模板
- `wall_entry` 图标会随城墙等级变化，只作为备用锚点
- 面板可能记住上次位置，不要只向一个方向滑动

### 明明还有城墙却提前结束

结束只认两种证据：

1. 识别到的城墙行全部读数为 0
2. 数量未知且批量界面连续两次打不开

早期版本把“建造面板已打开但找不到城墙行”当成完成，城墙图标等级与模板不同时会误判。现在这种情况会报错进入 recover，并在日志里提示检查 `wall_row_label` / `wall_entry`。

检查 `runtime/mumu/logs` 里“城墙可升级 N 段”的读数。如果数量被误读成 0，先确认数量 ROI 只覆盖数字区域，再用 Vision Studio 验证数字识别。使用 `wall_row_label` 时数量 ROI 从文字右侧自动推算；使用 `wall_entry` 时由 `remaining_offset` 控制。

### 数量一直读不到

任务会按 `unknown_batch_size` 小批量升级，不会结束。日志里会出现“无法读取城墙可升级数量”。用 `remaining_offset` 调整相对城墙图标的 ROI；不同分辨率或 UI 皮肤下数字位置可能变化。

### 升级按钮点错

金币和圣水按钮位置固定，配置 `gold_button`、`elixir_button`。这些坐标只适用于 X1 布局；单批选到 10 段以上时游戏会把金币升级按钮移到上排，所以 `max_batch` 默认限制为 9。如果分辨率不是 1920x1080，需要重新标定。

### 成本识别错误

在 X1 状态读取单段成本，避免选 10 段后小字号误读。读不到时用 `cost_per_wall` 兜底。

不同城墙等级成本不同，等级越高数字越长。如果日志里的成本明显偏小，检查 `assets/assets.yaml` 里 `wall_cost_gold`、`wall_cost_elixir` 的 ROI 是否截断了高位数字；用 Vision Studio 调整宽度后重试。

### 升级后没有扣资源

确认按钮优先用 `wall_confirm` 模板定位；模板没有命中时认为升级没有发生并抛错，不会误扣资源。检查 `runtime/wall-buttons.json` 和当前分辨率。
