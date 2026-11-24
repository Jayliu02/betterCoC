# 进攻刷资源 raid

## 目标

循环执行：搜索对手 → 读取资源 → 不足则换下一个 → 达到阈值自动战斗 → 回营。

任务名：`raid`，实现：[bettercoc/tasks/raid.py](../bettercoc/tasks/raid.py)。

## 状态机

```text
prepare ──> raid ──> decide ──> raid ...
                │
                └── 达到轮数/时长 ──> finish
```

异常进入 `recover`，尝试回主城后继续；超过 `max_errors` 结束。

## 流程

1. `prepare`：回主城，关闭欢迎弹窗、侧边面板、结算页
2. 点击 `home_attack`
3. 点击 `attack_find_match`（常规战“搜索对手”）
4. 等待 `army_attack`，点击“进攻！”
5. 等待 `scout_next`，进入侦察界面
6. 读取左上角三个数字：金币、圣水、暗黑
7. 金币 + 圣水 < `min_total` 时点击 `scout_next`，最多 `max_next` 次
8. 达标后点击 `auto_battle`
9. 等待 `battle_return_home`，点击“回营”
10. `decide` 累计轮数

`auto_battle` 不存在时回退到手动流程：点 `scout_attack`，等 `battle_end`，按 `army` 配置下兵，再结束战斗。

## 资源判断

当前中文版侦察界面左上角：

```text
可获得的战利品:
金币   1,824,001
圣水     831,319
暗黑       6,584
```

ROI：

| 项 | ROI |
| --- | --- |
| `loot_gold` | `[70, 125, 250, 50]` |
| `loot_elixir` | `[70, 195, 250, 50]` |
| `loot_dark` | `[70, 265, 200, 50]` |

数字识别使用 [bettercoc/digits.py](../bettercoc/digits.py)，模板在 `assets/digits`。流程：

1. 白色像素阈值
2. 连通域分割
3. 去掉宽度/高度异常和纵向离群的图标
4. 每个数字归一化到 24x32
5. 与 0-9 模板比较，取最高相似度
6. 拼成数字串

一次截图内读完三个数字，然后立即点击“自动战斗”，避免 30 秒侦察倒计时超时。

## 识别项

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `home_attack` | 模板 | 主城“战斗” |
| `home_popup_close` | 模板 | 欢迎弹窗 X |
| `side_panel_close` | 模板 | 侧边面板 X |
| `attack_find_match` | 模板 | 搜索对手 |
| `army_attack` | 模板 | 军队确认页“进攻！” |
| `scout_next` | 模板 | 下一个 |
| `auto_battle` | 模板 | 自动战斗 |
| `battle_return_home` | 模板 | 回营 |
| `game_stop` | 模板 | 断线弹窗“重新载入游戏” |
| `loot_gold` / `loot_elixir` / `loot_dark` | 数字 | 资源 |

备用：`scout_cancel`（取消侦察）、`scout_attack` / `battle_end`（手动兜底）、`dialog_ok`、`attack_multiplayer`。

## 断线重连

断线弹窗“还在吗？”出现时，`game_stop` 命中“重新载入游戏”，任务点击后等待 `home_attack`，默认最多 90 秒（`runtime.reload_timeout`）。检查点：

- `_ensure_home` 每次回主城
- `_wait_battle_result` 每 5 秒
- `wall_upgrade` 和 `farm_wall` 的回主城流程
- `resources.refresh` 读取资源前的回主城流程

重载会中断当前战斗，任务回到主界面后继续下一轮。

## 配置

```yaml
task:
  name: raid
  raid:
    max_cycles: 20
    max_runtime_min: 30
    max_errors: 3
    match_timeout: 45
    battle_start_timeout: 45
    battle_timeout: 240
    result_timeout: 20
    end_battle_after_deploy: true
    loot_check: true
    min_total: 2000000
    max_next: 15
    min_gold: 0
    min_elixir: 0
    min_dark: 0
    auto_battle: true
    army:
      troop_slots: []
      deploy_points: []
      waves: 1
      tap_delay_ms: 120
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `max_cycles` | 20 | 进攻轮数，0 表示只受时长限制 |
| `max_runtime_min` | 60 | 最长运行分钟 |
| `max_errors` | 3 | 恢复次数上限 |
| `match_timeout` | 45 | 匹配对手超时 |
| `battle_start_timeout` | 45 | 点击进攻后等待战斗界面 |
| `battle_timeout` | 240 | 自动战斗等待结算 |
| `result_timeout` | 20 | 手动结束战斗后等待结算 |
| `end_battle_after_deploy` | true | 手动流程下兵后结束战斗 |
| `loot_check` | true | 是否读取资源 |
| `min_total` | 2000000 | 金币 + 圣水阈值 |
| `max_next` | 15 | 最多换几个对手 |
| `min_gold` / `min_elixir` / `min_dark` | 0 | 单项额外阈值 |
| `auto_battle` | true | 点自动战斗 |
| `army` | 空 | 手动下兵兜底 |

`runtime.reload_timeout`（默认 90 秒）控制断线重载后等待主界面的上限。`max_runtime_min` 按单次 raid 任务计时，`farm_wall` 内每轮都会重新计时。

## 实测

MuMu 中文版一轮：

```text
对手资源 {'gold': 916323, 'elixir': 923678, 'dark': 6920}，合计 1840001，筛选结果 不通过
资源不足，换下一个对手
对手资源 {'gold': 1454941, 'elixir': 1006021, 'dark': 8930}，合计 2460962，筛选结果 通过
使用自动战斗
第 1 次进攻结束
任务: raid
状态: success
结果: 1 轮，进攻 1 次
```

从匹配到目标（01:36:05）到点击自动战斗（01:36:05）在同一秒完成，远低于 30 秒倒计时。

回主城后金币从 8,374,550 增加到 9,842,491，圣水从 8,719,599 增加到 9,740,620。

## 常见问题

### 读到 4,258,574 这类异常值

数字 ROI 里混入了图标。数字识别会按纵向位置剔除离群连通域；如果新界面仍出现，缩小 ROI 或重新生成模板。

### 自动战斗点不到

模板必须包含“自动战斗”文字和人物头像，且不要加固定 ROI，因为按钮位置会随底部按钮数量变化。当前模板全屏匹配。

### 30 秒内来不及点

任务在匹配到对手后立即读三个数字并点击自动战斗。不要插入截图保存、调试日志或人工确认。`probe` 只用于校准，不参与运行流程。

### 资源一直不达标

调低 `min_total`，或增大 `max_next`。`max_next` 次仍不达标时任务会取消本次侦察并回主城。
