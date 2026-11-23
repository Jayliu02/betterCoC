# 城墙升级 wall_upgrade

## 状态

已实现，MuMu 中文版实测通过。

任务名：`wall_upgrade`，实现：[bettercoc/tasks/wall_upgrade.py](../bettercoc/tasks/wall_upgrade.py)。

运行：

```powershell
bettercoc --config config/mumu.yaml run --task wall_upgrade --trace
```

## 流程

```text
prepare ──> open ──> select ──> upgrade ──> decide
   ▲                                            │
   └──────────────── 继续下一批 ────────────────┘

任意状态异常 -> recover -> prepare
```

### prepare

- 回主城，关闭侧边栏和欢迎弹窗
- 读取右上角金币、圣水、暗黑
- 写入 `runtime/resource-state.json`
- 记住任务开始时的资源

### open

1. 点击主城右下角“建造”
2. 在“建筑和英雄”列表上下滑动，找到“城墙”入口
3. 点击城墙入口
4. 等待城墙面板，点击“升级更多”
5. 等待批量选择面板

滑动策略：先向上找，再向下找，避免面板记住上次滚动位置。

### select

1. 在 X1 状态下读取每段升级成本（金币/圣水）
2. 计算可负担段数
3. 按 `batch_size`、剩余 `max_upgrades`、可负担段数取最小值
4. 用“添加城墙 +10 / +1”选到目标段数
5. 金币足够用金币，否则用圣水

### upgrade

1. 点击金币或圣水升级按钮
2. 等待“升级城墙”确认页
3. 点击“确定”
4. 扣减内存中的资源、累计升级段数
5. 关闭侧边栏，回主城

### decide

- 达到 `max_upgrades` 结束
- 资源不足结束
- 否则回到 `prepare` 继续下一批

## 识别项

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `build_button` | 模板 | 主城右下角“建造” |
| `wall_entry` | 模板 | 建造栏里的城墙图标 |
| `wall_more` | 模板 | 城墙面板“升级更多” |
| `wall_add_10` | 模板 | 批量选择“+10” |
| `wall_add_1` | 模板 | 批量选择“+1” |
| `wall_confirm` | 模板 | 升级确认“确定” |
| `home_gold` / `home_elixir` / `home_dark` | 数字 | 主城资源 |
| `wall_cost_gold` / `wall_cost_elixir` | 数字 | 每段城墙成本 |
| `side_panel_close` | 模板 | 关闭侧边栏 |
| `home_popup_close` | 模板 | 关闭欢迎弹窗 |

旧的 `wall_panel`、`wall_upgrade`、`wall_confirm_blocked` 来自地图点墙流程，已移除。

## 资源策略

用户要求：金币和圣水都可以，只要存量足够。

实现：

- 在批量选择 X1 状态读取单段成本
- 总成本 = 单段成本 × 段数
- `prefer_currency: auto`：金币够就用金币，否则用圣水
- 两种货币都不够时，按可负担段数缩减批次
- 每批确认成功后扣减内存资源
- 每轮回主城重新读取真实资源，避免读数漂移

### 剩余城墙和最大批量

进入建造栏后，城墙行会显示剩余数量，例如 `城墙 x237`。任务在点击入口前读取该数字，作为 `wall_remaining`。

打开建造栏后默认在初始位置，任务只向下滚动查找城墙，不再先反向滚动。

`batch_size: 0` 表示按当前资源计算最大数量：

```text
可升级数量 = max(gold // cost_gold, elixir // cost_elixir)
batch = min(剩余城墙, 可升级数量)
```

### 金币/圣水连续升级

`farm_wall` 预检使用 `drain_all` 模式：

1. 金币够先用金币，按金币可升级数量升完
2. 金币不足后，在保持打开的侧边栏再次点击城墙
3. 选择圣水继续升级
4. 两种货币都低于单段成本才停止
5. 不需要重新点“建造”，也不需要重新从初始位置滚动

状态文件：

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
  "wall_upgrades": 10
}
```

## 配置

```yaml
task:
  wall_upgrade:
    max_upgrades: 10
    batch_size: 10
    max_cycles: 10
    max_runtime_min: 15
    max_errors: 2
    cost_per_wall: 600000
    prefer_currency: auto
    scroll_times: 10
    scroll_duration_ms: 400
    settle_ms: 1500
    gold_button: [487, 930]
    elixir_button: [707, 930]
    state_file: runtime/resource-state.json
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `max_upgrades` | 10 | 本次最多升级几段墙 |
| `batch_size` | 10 | 每批选择几段，最多 300 |
| `cost_per_wall` | 600000 | 读不到成本时的兜底单价 |
| `prefer_currency` | auto | `auto` / `gold` / `elixir` |
| `scroll_times` | 10 | 建造栏滑动最大次数 |
| `settle_ms` | 1500 | 确认后的等待 |
| `gold_button` | [487,930] | 金币升级按钮坐标 |
| `elixir_button` | [707,930] | 圣水升级按钮坐标 |

## 实测

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

- 先向上滑，再向下滑
- 确认 `wall_entry` 模板来自当前语言/皮肤
- 面板可能记住上次位置，不要只向一个方向滑动

### 升级按钮点错

金币和圣水按钮位置固定，配置 `gold_button`、`elixir_button`。如果分辨率不是 1920x1080，需要重新标定。

### 成本识别错误

在 X1 状态读取单段成本，避免选 10 段后小字号误读。读不到时用 `cost_per_wall` 兜底。

### 升级后没有扣资源

只有确认页出现并点击“确定”后才计数和扣减。确认页模板失效时任务会失败，不会虚报升级。
