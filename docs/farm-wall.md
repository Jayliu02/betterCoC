# 打资源 + 升墙 farm_wall

## 启动预检

进入主循环前先判断当前能不能升级：

1. 读取状态里的城墙剩余数量和单段成本
2. 金币或圣水任一足够单段成本，执行一次 `wall_upgrade`
3. `wall_upgrade` 先金币、后圣水，把当前能升的墙升完
4. 资源不足或城墙为 0 时跳过
5. 预检结束后再进入“进攻到满 → 升墙”的主循环

实测：

```text
预检: 当前资源可升级城墙，先清空可用金币/圣水
当前资源可升级 8 段
选择 2 段城墙，使用 金币
reopen
选择 8 段城墙，使用 圣水
预检升级 10 段
主流程进攻 1 次
```

预检使用 `drain_all` 模式：先按金币可升级数量升完金币，再切换到圣水，直到两种货币都不足单段成本。预检使用 `task.wall_upgrade.cost_per_wall` 作为成本兜底；如果界面读数异常，会拒绝小于 10,000 的成本并回到配置值。

## 目标

把 `raid` 和 `wall_upgrade` 串成一个循环：

1. 资源未满时进攻
2. 重复进攻，直到金币和圣水都达到设定上限
3. 资源满后，读取当前单段城墙成本，计算最多能升几段，一次批量升完
4. 升级后资源下降，如果城墙还没升完，回到第 1 步继续打
5. 目标是一直运行到建造-城墙栏剩余数量为 0；资源不足时回第 1 步，只有没有可升级城墙或确实无法继续时才退出

任务名：`farm_wall`，实现：[bettercoc/tasks/farm_wall.py](../bettercoc/tasks/farm_wall.py)。

```powershell
bettercoc --config config/mumu.yaml run --task farm_wall --trace
```

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
4. 点击金币、圣水、暗黑，读取提示里的“最大储量”
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
| 城墙 剩余 237 / 300   已升级 63        |
| 升级城墙 4 段                               |
+------------------------------------------+
```

单独查看：

```powershell
bettercoc --config config/mumu.yaml status
bettercoc --config config/mumu.yaml status --live
```

`status` 读状态文件，`status --live` 回主城截图重新读取。

## 判断“资源已满”

读取主城右上角金币和圣水：

```text
gold >= GOLD_MAX 且 elixir >= ELIXIR_MAX
```

`GOLD_MAX`、`ELIXIR_MAX` 来自点击资源后的“最大储量”提示；读取失败时使用 `full_gold`、`full_elixir` 配置兜底。当前大本营金币/圣水上限都是 10,000,000，暗黑上限 200,000。

资源读数使用 `home_gold`、`home_elixir`、`home_dark` 数字识别。ROI 已避开右侧资源图标，低数值如 234,789 也能准确读取。

## 判断“还有城墙”

进入建造栏，城墙行会显示剩余可升级数量，例如：

```text
城墙 x237
```

`wall_upgrade` 在点击城墙入口前读取这个数字，作为 `wall_remaining` 返回。

已升级数量：

```text
walls_done = total_walls - wall_remaining + 本次升级数量
```

默认 `total_walls: 300`。读到剩余数量后会校准状态文件，避免历史计数漂移。

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
batch = min(剩余城墙, 可升级数量)
```

`wall_batch: 0` 表示不额外限制，直接按资源计算最大数量。当前 7,500,000 金币、7,491,186 圣水、单价 600,000 时：

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
  "walls_done": 63,
  "wall_upgrades": 4,
  "wall_remaining": 237
}
```

字段：

| 字段 | 说明 |
| --- | --- |
| `gold` / `elixir` / `dark` | 最近一次读取的主城资源 |
| `walls_done` | 已升级城墙数量，读城墙行后校准 |
| `wall_upgrades` | 最近一次 `wall_upgrade` 升级数量 |
| `wall_remaining` | 最近一次读到的城墙行剩余数量 |
| `farm_cycles` | 调度循环数 |
| `farm_raids` | 调度内进攻次数 |
| `farm_wall_upgrades` | 调度内升级城墙数量 |

## 配置

```yaml
task:
  farm_wall:
    full_gold: 10000000
    full_elixir: 10000000
    total_walls: 300
    wall_batch: 0
    max_cycles: 0
    max_runtime_min: 0
    max_resource: 20000000
    state_file: runtime/resource-state.json
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `full_gold` | 10000000 | 金币满值 |
| `full_elixir` | 10000000 | 圣水满值 |
| `total_walls` | 300 | 总城墙数 |
| `wall_batch` | 0 | 0 表示按资源算最大数量 |
| `max_cycles` | 0 | 0 表示不限制，一直运行到没有可升级城墙 |
| `max_runtime_min` | 0 | 0 表示不限制；需要停止时 Ctrl+C |
| `max_resource` | 20000000 | 资源读数上限，超过认为仍在结算动画 |

## 实测

两轮调度：

```text
资源 金币 4,710,156 / 圣水 3,740,620 / 暗黑 207,500，已升级城墙 13/300
第 1 轮：进攻 1 次
第 2 轮：资源已满，升级城墙 2 段
结果：2 轮调度，进攻 1 次，升级城墙 2 段，累计 15/300
```

单段成本读取：

```text
单段成本 金币 600000 / 圣水 600000，当前资源可升级 1 段
选择 1 段城墙，成本 金币 600000 / 圣水 600000，使用 圣水
剩余资源不足单段成本，结束本轮城墙升级
```

最大数量读取：

```text
当前资源可升级 12 段
```

当前城墙行显示 `城墙 x237`，状态校准为 `walls_done=63`。

## 注意

- 资源满值按当前大本营储量配置；升级大本营后需要调整
- 城墙总数按 300 配置；不同大本营可能不同
- 城墙行数量是当前等级可升级数量，全部满级后会显示剩余 0
- 单段成本从界面读取，金币/圣水分别计算
- 结算动画期间资源读数可能异常，代码会等待、限制上限并回退上一次有效值
