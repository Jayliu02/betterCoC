# 打资源 + 升墙 farm_wall

## 目标

把 `raid` 和 `wall_upgrade` 串成一个循环：

1. 初始资源总和超过阈值：先执行一次 `wall_upgrade`
2. 未超过阈值：打资源，直到金币 + 圣水超过阈值
3. 达到阈值后才升墙，一次升级多段城墙
4. 重复“打资源 → 达到阈值 → 批量升墙”，直到 `wall_upgrade` 读到“没有可升级城墙”
5. 默认到此结束；`farm_after_complete: true` 时再继续打资源到阈值

是否升满只由游戏界面决定，不用配置的总城墙数推算。不同大本营城墙数量不同、存在多个城墙等级时都不需要改配置。

任务名：`farm_wall`，实现：[bettercoc/tasks/farm_wall.py](../bettercoc/tasks/farm_wall.py)。

```powershell
bettercoc --config config/mumu.yaml run --task farm_wall --trace
```

## 调度

```text
读取初始资源
    │
    ├── 总和 > 阈值：先升墙 ──> 已无城墙？──> 结束
    │
    └── 循环：
         打一轮资源
           │
         总和 > 阈值？
           ├── 否：继续打资源
           └── 是：升墙（一次升级多段，WallUpgradeTask，max_upgrades=0）
                 │
               读到“无可升级城墙”？──> 结束
                 │
               否：继续下一轮
```

达到阈值后，`wall_upgrade` 会连续升级多个城墙，直到资源不足、达到循环上限或读到没有城墙为止；`farm_wall` 在资源总和未达到阈值时只打资源，不调用升墙。

## 完成判断

`farm_wall` 不再使用 `total_walls`、`walls_done`。完成条件是 `wall_upgrade` 返回的观测结果：

- `wall_remaining == 0`：识别到的城墙行显示没有可升级城墙
- `wall_complete == 1`：所有城墙行读数为 0，或数量未知且批量界面连续打不开

找不到城墙行时 `wall_upgrade` 会报错，`farm_wall` 按失败处理，不会把“模板没匹配到”当成城墙已升满。

状态文件里如果还保留历史的 `wall_remaining` / `wall_complete`，只用于 CMD 显示，不参与本轮完成判断。每次运行都会重新进入建造栏读取，升级大本营后不会因为历史“已完成”而跳过。

## 卡住自动重进

资源足够、还有可升级城墙，但 `wall_upgrade` 一次也没有升级成功时，`farm_wall` 会强制退出并重新启动游戏：

1. `am force-stop` 关闭游戏进程
2. `monkey` 重新启动
3. 关闭“欢迎回家”开屏弹窗
4. 等待 `home_attack` 回到主界面
5. 刷新资源，重新进入升墙流程

```yaml
runtime:
  game_package: com.tencent.tmgp.supercell.clashofclans
  restart_timeout: 180
task:
  farm_wall:
    max_restarts: 5
```

游戏包名以实际配置为准。达到 `max_restarts` 仍无法升级时退出。实测重进并关闭开屏弹窗耗时 19 秒。

“资源是否足够”优先使用 `wall_upgrade` 本次读到的单段成本；还没有读到成本时用 `task.wall_upgrade.cost_per_wall` 兜底。不同等级的城墙成本不同，所以第一次升墙后会用实际读数。

`max_runtime_min` 按每个任务实例计时，不使用进程总运行时间。

## 全局资源变量

`bettercoc/resources.py`：

```python
GOLD = 0
ELIXIR = 0
DARK = 0
GOLD_MAX = 0
ELIXIR_MAX = 0
DARK_MAX = 0
LOADED = False
MAX_LOADED = False
```

首次加载脚本时：

1. 回主城，关闭侧边栏和欢迎弹窗
2. 用双指 pinch 缩小视角到最小
3. 截图读取 `home_gold`、`home_elixir`、`home_dark`
4. 依次点击金币、圣水、暗黑，读取提示里的“最大储量”；每次读取后先关闭提示，避免上一个弹窗挡住下一个资源
5. 失败重试；最大储量读取失败时用配置兜底
6. 写入 `runtime/resource-state.json`

之后：

- 进攻结束回城：`resources.refresh(ctx)` 更新全局值
- 升墙确认成功：`resources.adjust(gold=-cost)` 或 `resources.adjust(elixir=-cost)`
- 任务决策读取 `resources.snapshot()`，不再反复截图读资源

`bettercoc run` 在任务启动前调用 `ensure_loaded`；`farm_wall` 和 `wall_upgrade` 内部也会确保已加载。

## CMD 状态显示

首次读取、进攻后刷新、升墙扣费、城墙数量变化时，CMD 打印资源面板：

```text
+---------------- 资源状态 ----------------+
| 金币 234,789 / 10,000,000
| 圣水 9,400,000 / 10,000,000
| 暗黑 207,500 / 200,000
| 城墙 可升级 237 段
| 本次升级 63 段
| 升级城墙 4 段
+------------------------------------------+
```

没有可升级城墙时显示：

```text
| 城墙 已无可升级项
```

单独查看：

```powershell
bettercoc --config config/mumu.yaml status
bettercoc --config config/mumu.yaml status --live
```

`status` 读状态文件，`status --live` 回主城截图重新读取。

## 判断资源和阈值

读取主城右上角金币和圣水：

```text
总和 = gold + elixir
阈值 = (GOLD_MAX + ELIXIR_MAX) × threshold_ratio
```

`GOLD_MAX`、`ELIXIR_MAX` 来自点击资源后的“最大储量”提示；读取失败时使用 `full_gold`、`full_elixir` 配置兜底。`config/mumu.yaml` 当前上限都是 15,000,000，阈值 90% 即金币 + 圣水 > 27,000,000。

资源总和未超过阈值时，`farm_wall` 只打资源，不调用 `wall_upgrade`；超过阈值后才进入建造栏，一次升级多段城墙。`wall_upgrade` 也会收到同一个 `min_total`，低于阈值时直接结束，避免绕过调度单独升墙。

资源读数使用 `home_gold`、`home_elixir`、`home_dark` 数字识别。ROI 已避开右侧资源图标，低数值如 234,789 也能准确读取。

## 判断“还有城墙”

进入建造栏，城墙行会显示当前可升级的那一组城墙数量，例如：

```text
城墙 x237
```

`wall_upgrade` 在点击城墙入口前读取这个数字，作为 `wall_remaining`。读到 0 或列表里没有城墙入口，就是“没有可升级城墙”。

存在多个等级时，某一等级升完后下一次会读到下一等级的数量，因此每次升级后都重新读一次，不做 `总数 - 已完成` 的推算。

## 计算最大升级数量

进入“升级更多”后，先在 X1 状态读取单段成本：

```text
单段成本 金币 600000 / 圣水 600000
```

默认金币和圣水单价相同，代码分别计算：

```text
可升级数量 = max(gold // cost_gold, elixir // cost_elixir)
```

本次批量：

```text
batch = min(城墙数量, 可升级数量, batch_size, max_upgrades 剩余, 30)
```

`wall_batch: 0` 表示不额外限制。当前 7,500,000 金币、7,491,186 圣水、单价 600,000 时：

```text
当前资源可升级 12 段
选择 12 段城墙，成本 金币 7200000 / 圣水 7200000，使用 金币
```

金币不足时自动改用圣水。

## 状态文件

`runtime/resource-state.json`：

```json
{
  "gold": 234789,
  "elixir": 9400000,
  "dark": 207500,
  "gold_max": 10000000,
  "elixir_max": 10000000,
  "dark_max": 200000,
  "wall_remaining": 237,
  "wall_upgraded": 63,
  "wall_complete": false,
  "wall_upgrades": 4,
  "farm_cycles": 7,
  "farm_raids": 7,
  "farm_wall_upgrades": 20
}
```

| 字段 | 说明 |
| --- | --- |
| `gold` / `elixir` / `dark` | 最近一次读取的主城资源 |
| `wall_remaining` | 最近一次读到的可升级数量 |
| `wall_upgraded` | 本次调度内升级数量 |
| `wall_complete` | 是否已读到“没有可升级城墙” |
| `wall_upgrades` | 最近一次 `wall_upgrade` 升级数量 |
| `farm_cycles` | 调度循环数 |
| `farm_raids` | 调度内进攻次数 |
| `farm_wall_upgrades` | 调度内升级城墙数量 |

## 配置

```yaml
task:
  farm_wall:
    full_gold: 10000000
    full_elixir: 10000000
    wall_batch: 0
    max_cycles: 0
    max_runtime_min: 0
    max_restarts: 5
    threshold_ratio: 0.9
    max_raid_retries: 3
    farm_after_complete: false
    state_file: runtime/resource-state.json
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `full_gold` | 10000000 | 金币满值兜底 |
| `full_elixir` | 10000000 | 圣水满值兜底 |
| `wall_batch` | 0 | 0 表示按资源和城墙数量算最大批次 |
| `max_cycles` | 0 | 0 表示不限制，直到没有可升级城墙 |
| `max_runtime_min` | 0 | 0 表示不限制；需要停止时 Ctrl+C |
| `max_restarts` | 5 | 卡住时最多重进游戏几次，0 表示不限制 |
| `threshold_ratio` | 0.9 | 资源总和阈值比例 |
| `max_raid_retries` | 3 | 连续 0 进攻次数的重试上限 |
| `farm_after_complete` | false | 城墙升满后是否继续打资源到阈值 |
| `max_resource` | 20000000 | 资源读数上限，超过认为仍在结算动画 |

内层 `raid`、`wall_upgrade` 的 `max_runtime_min` 按各自任务实例计时；整体运行时长用 `farm_wall.max_runtime_min` 控制。

## 实测

以下是旧版固定总数流程的 MuMu 运行记录，资源与按钮部分仍然有效；新的“按建造读数结束”循环尚未真机验证。

2026-11-24 一次完整运行：

```text
7 次进攻
最后 20 段：16 段金币 + 1 段圣水
城墙剩余 0
```

状态文件：

```text
farm_raids: 7
farm_wall_upgrades: 20
wall_remaining: 0
wall_complete: true
```

## 注意

- 资源阈值按当前大本营储量配置；升级大本营后需要调整
- 城墙是否升满按界面读数判断，不再配置总城墙数
- 城墙行数量是当前可升级组的数量；一组升完后会读到下一组
- 单段成本从界面读取，金币/圣水分别计算
- 结算动画期间资源读数可能异常，代码会等待、限制上限并回退上一次有效值
