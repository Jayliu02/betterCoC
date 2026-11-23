# betterCoC

参考 [BetterGI](https://www.bettergi.com/) 的图像识别分层，为《部落冲突》(Clash of Clans) 搭建的可扩展自动化框架。

当前包含三个任务：

- `raid`：搜索对手、按资源阈值筛选、自动战斗、回营循环。已完成 MuMu 实测。
- `wall_upgrade`：城墙升级，已完成。主界面“建造” → 滑动建造栏 → 城墙 → 批量选择 → 比较金币/圣水余额 → 确认升级。
- `farm_wall`：组合调度。资源未满时进攻，金币和圣水都满后按当前单段成本计算最大升级数量，资源降下来后继续进攻。

![模拟器主界面](docs/images/demo-home.png)

## 当前状态

- 截图后端：ADB、图片文件夹、静态图片
- 画面统一归一化到 1920x1080，ROI、模板、点击坐标共用一套坐标
- 模板匹配：ROI、阈值、灰度/三通道、多尺度、Alpha 遮罩、颜色遮罩、NMS
- 颜色识别：HSV / BGR
- OCR：Tesseract 可选
- 数字模板识别：无需 Tesseract 读取金币、圣水、暗黑数量
- 全局资源：首次加载时回主城、双指缩放到最小视角，读取金币/圣水/暗黑及各自最大储量；`GOLD`、`ELIXIR`、`DARK`、`GOLD_MAX`、`ELIXIR_MAX`、`DARK_MAX` 全局共享
- 资源清单：YAML 声明式识别项，模板懒加载
- 运行时：等待、点击、随机抖动、dry-run、停止信号
- `raid`：状态机、错误恢复、资源筛选、自动战斗、循环上限
- `wall_upgrade`：建造栏入口、滑动查找、批量 +10/+1、金币/圣水余额对比、确认升级、资源状态文件
- `farm_wall`：进攻到资源满 → 读单段成本 → 计算最大升级数量 → 批量升墙 → 资源不足继续进攻
- 运行到建造-城墙栏不再有可升级城墙为止
- 内置模拟器 `demo`，无需游戏即可跑攻击循环
- MuMu 实测：ADB 自动重连、实时截图、真实自动战斗、回营
- 单元测试与模拟器集成测试

真实游戏模板位于 `assets/templates`。仓库中的模板来自当前 MuMu 中文版账号，换账号、语言、分辨率或游戏 UI 后需要重新校准。

## 快速开始

要求 Python 3.10+。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
bettercoc demo --cycles 2
```

`demo` 会生成模拟截图、模板和配置，运行攻击循环，并输出：

```text
演示状态: success
演示结果: 2 轮，进攻 2 次
模拟器数据: 进攻 2 次，剩余金币 900,000，圣水 800,000
输出目录: ...\runtime\demo
```

## MuMu 接入

MuMu 15 的 ADB：

```text
C:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe
```

串口：

```text
127.0.0.1:16384
```

当前机器已写入 [config/mumu.yaml](config/mumu.yaml)。`AdbDevice` 会自动执行 `adb connect`，模拟器重启后不需要手动重连。

```powershell
bettercoc --config config/mumu.yaml doctor
bettercoc --config config/mumu.yaml capture -o runtime/mumu/live.png
bettercoc --config config/mumu.yaml probe --save runtime/mumu/probe.png
```

## 进攻流程 raid

```text
prepare ──> raid ──> decide ──> raid ...
                │
                └── 达到轮数/时长 ──> finish
```

1. `prepare`：回主城，关闭欢迎弹窗、侧边面板、结算页
2. 点击主城左下角“战斗”
3. 点击“常规战”的“搜索对手”
4. 在“我的军队”确认页点击“进攻！”
5. 等待侦察界面
6. 读取左上角金币、圣水、暗黑
7. 金币 + 圣水 < `min_total` 时点“下一个”，最多 `max_next` 次
8. 达标后点“自动战斗”
9. 等待结算，点“回营”
10. 累计轮数，继续或结束

实测规则：金币 + 圣水 ≥ 2,000,000 才进攻。数字识别由 `assets/digits` 的模板完成，一帧内读完三个数字并立即点击，避免 30 秒侦察倒计时超时。最终实测一轮：第一个目标 184 万被跳过，第二个目标 246 万通过，读取与点击自动战斗在同一秒完成。

细节见 [docs/raid.md](docs/raid.md)。

## 图像识别项

当前 `raid` 需要的识别项：

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `home_attack` | 模板 | 主城左下角“战斗”按钮 |
| `home_popup_close` | 模板 | 欢迎回家弹窗的红色 X |
| `side_panel_close` | 模板 | 侧边“建筑和英雄”面板的 X |
| `attack_find_match` | 模板 | 常规战“搜索对手” |
| `army_attack` | 模板 | 我的军队页“进攻！” |
| `scout_next` | 模板 | 侦察界面“下一个” |
| `auto_battle` | 模板 | 侦察界面“自动战斗” |
| `battle_return_home` | 模板 | 结算界面“回营” |
| `loot_gold` | 数字 | 左上角金币数量 |
| `loot_elixir` | 数字 | 左上角圣水数量 |
| `loot_dark` | 数字 | 左上角暗黑数量 |

备用识别项：`scout_attack`、`battle_end`、`scout_cancel`、`dialog_ok`、`attack_multiplayer`。自动战斗流程不需要 `scout_attack` 和 `battle_end`。

`wall_upgrade` 额外需要：

| 名称 | 类型 | 用途 |
| --- | --- | --- |
| `build_button` | 模板 | 主城右下角“建造” |
| `wall_entry` | 模板 | 建造栏里的城墙图标 |
| `wall_more` | 模板 | 城墙面板“升级更多” |
| `wall_add_10` / `wall_add_1` | 模板 | 批量加墙 |
| `wall_confirm` | 模板 | 确认升级 |
| `home_gold` / `home_elixir` / `home_dark` | 数字 | 主城资源 |
| `wall_cost_gold` / `wall_cost_elixir` | 数字 | 每段城墙成本 |

颜色项 `wall_upgrade_available` 已从当前清单移除；两个任务都直接使用模板和数字识别。

## 配置

`config/mumu.yaml` 关键项：

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
    loot_check: true
    min_total: 2000000
    max_next: 15
    auto_battle: true
    army:
      troop_slots: []
      deploy_points: []
```

| 配置 | 说明 |
| --- | --- |
| `task.raid.max_cycles` | 进攻轮数，0 表示只受时长限制 |
| `task.raid.min_total` | 金币 + 圣水最低值，默认 200 万 |
| `task.raid.max_next` | 最多换多少个对手 |
| `task.raid.loot_check` | 是否读取资源并筛选 |
| `task.raid.auto_battle` | 是否点“自动战斗” |
| `task.raid.battle_timeout` | 等待战斗结束的超时 |
| `task.raid.army` | 手动下兵兜底坐标 |

完整说明见 [docs/raid.md](docs/raid.md)。

## 城墙升级 wall_upgrade

流程：

1. `prepare`：回主城，关闭侧边栏/欢迎弹窗
2. 读取主城右上角金币、圣水、暗黑，写入 `runtime/resource-state.json`
3. 点击右下角“建造”
4. 在“建筑和英雄”列表上下滑动，找到“城墙”入口
5. 点击入口，进入城墙升级界面
6. 点击“升级更多”，进入批量选择
7. 读取每段成本，按金币/圣水余额计算能升几段
8. 用“添加城墙 +10 / +1”选到目标数量
9. 优先金币，金币不足时改用圣水
10. 点击升级，确认，扣减内存中的资源
11. 回主城，继续下一批，直到达到 `max_upgrades` 或资源不足

实测：

- 2 段：花费金币 1,200,000，金币 5,800,000 → 4,600,000
- 10 段：金币不足，自动改用圣水 6,000,000，圣水 9,740,620 → 3,740,620
- 状态文件记录升级数量、前后资源、各货币花费

```yaml
task:
  wall_upgrade:
    max_upgrades: 10
    batch_size: 10
    cost_per_wall: 600000
    prefer_currency: auto
    gold_button: [487, 930]
    elixir_button: [707, 930]
```

运行：

```powershell
bettercoc --config config/mumu.yaml run --task wall_upgrade --trace
```

完整说明见 [docs/wall-loop.md](docs/wall-loop.md)。

## 打资源 + 升墙 farm_wall

目标：一直运行到建造-城墙栏里没有可升级城墙。

调度循环：

0. 启动预检：读取当前城墙数量和单段成本；当前金币或圣水足够时，先按金币→圣水把能升的墙升完
1. 预检后资源未满：调用 `raid` 打一轮
2. 重复，直到金币和圣水都达到 `full_gold` / `full_elixir`
3. 资源满：进入建造栏，读取“城墙 xN”剩余数量
4. 在 X1 状态读取单段成本
5. 按 `max(gold // cost_gold, elixir // cost_elixir)` 计算最多能升几段
6. 一次批量升级最大数量
7. 升级后资源下降且城墙未完成：回到第 1 步
8. 城墙完成，或资源不足且无法继续升级：退出

```yaml
task:
  farm_wall:
    full_gold: 10000000
    full_elixir: 10000000
    total_walls: 300
    wall_batch: 0
    max_cycles: 0
    max_runtime_min: 0
```

`wall_batch: 0` 表示按资源计算最大数量。

运行：

```powershell
bettercoc --config config/mumu.yaml run --task farm_wall --trace
```

实测启动预检：金币 1,697,541、圣水 5,164,589，先升 2 段金币 + 8 段圣水，把金币/圣水都用到不足单段成本；随后主流程进攻 1 次。城墙剩余从 219 降到 209。

完整说明见 [docs/farm-wall.md](docs/farm-wall.md)。

## 全局资源

`bettercoc/resources.py` 保存全局变量：

```python
GOLD
ELIXIR
DARK
GOLD_MAX
ELIXIR_MAX
DARK_MAX
LOADED
MAX_LOADED
```

首次加载：

1. 回主城，关闭侧边栏和弹窗
2. 用双指 pinch 把视角缩到最小
3. 截图读取右上角金币、圣水、暗黑
4. 依次点击金币、圣水、暗黑，读取提示里的“最大储量”
5. 读取失败重试，失败时使用配置的满值兜底
6. 写入 `runtime/resource-state.json`

`farm_wall` 的资源满判断优先使用全局最大值，不再固定 10,000,000。

任务启动前 `bettercoc run` 会调用 `ensure_loaded`；`wall_upgrade`、`farm_wall` 也会在需要时确保已加载。后续进攻回城后调用 `refresh` 更新，升墙扣费调用 `adjust` 扣减，不在界面打开时反复读资源。

命令行实时查看：

```powershell
bettercoc --config config/mumu.yaml status
bettercoc --config config/mumu.yaml status --live
```

`status` 读取状态文件，`status --live` 回主城重新截图读取。首次读取、进攻后刷新、升墙扣费、城墙数量变化时，CMD 会打印：

```text
+---------------- 资源状态 ----------------+
| 金币 234,789 / 10,000,000
| 圣水 9,400,000 / 10,000,000
| 暗黑 207,500 / 200,000
| 城墙 剩余 237 / 300   已升级 63        |
| 升级城墙 4 段                               |
+------------------------------------------+
```

## 架构

```text
Capture (ADB / Folder / Static)
        │
        ▼
normalize_frame → Screen 1920x1080 + Viewport
        │
        ▼
Vision ── Template / Color / Digits / OCR ──> Match
        │
        ▼
Context / Locator ── wait / click / tap / back / dry-run
        │
        ▼
StateMachine ── prepare / raid / decide / recover
        │
        ▼
Controller (ADB input)
```

| 模块 | 职责 |
| --- | --- |
| `bettercoc/geometry.py` | Rect、Viewport |
| `bettercoc/image.py` | Screen、归一化、读写图 |
| `bettercoc/spec.py` | Recognition 描述 |
| `bettercoc/template.py` | 模板匹配、掩码、多尺度、NMS |
| `bettercoc/color.py` | 颜色范围识别 |
| `bettercoc/digits.py` | 数字模板识别 |
| `bettercoc/ocr.py` | OCR 后端 |
| `bettercoc/assets.py` | YAML 资源清单 |
| `bettercoc/vision.py` | 统一识别入口 |
| `bettercoc/context.py` | 等待、点击、停止、截图 |
| `bettercoc/locator.py` | 链式定位器 |
| `bettercoc/state_machine.py` | 通用状态机 |
| `bettercoc/tasks/raid.py` | 进攻刷资源任务 |
| `bettercoc/tasks/wall_upgrade.py` | 城墙升级任务 |
| `bettercoc/tasks/farm_wall.py` | 进攻与升墙组合调度 |
| `bettercoc/resources.py` | 全局金币/圣水/暗黑读取与缓存 |
| `bettercoc/console.py` | CMD 资源状态面板 |
| `bettercoc/demo.py` | 内置模拟器 |
| `bettercoc/cli.py` | 命令行入口 |

设计细节见 [docs/architecture.md](docs/architecture.md)，MuMu 实测记录见 [docs/mumu-debug.md](docs/mumu-debug.md)。

## BetterGI 对照

| BetterGI | betterCoC |
| --- | --- |
| `captureGameRegion()` | `Context.screen()` |
| `RecognitionObject.templateMatch` | `Recognition(kind=TEMPLATE)` |
| `ImageRegion.find` / `findMulti` | `Vision.find` / `find_all` |
| `BvLocator.waitFor` / `tryWaitFor` | `Context.wait` / `try_wait`，`Locator` |
| `BvPage.getByText` | OCR 识别项 |
| `BvFlow` | `StateMachine` |
| 1080P 坐标 | `vision.canonical_size` |
| `Recognition.json` | `assets/assets.yaml` |

研究笔记见 [docs/bettergi-study.md](docs/bettergi-study.md)。

## 目录

```text
bettercoc/            框架代码
config/mumu.yaml      MuMu 配置
assets/assets.yaml    识别项清单
assets/templates/     模板
assets/digits/        数字模板
docs/                 设计、校准、任务说明
tests/                单元测试与模拟器集成测试
scripts/              本地运行与测试脚本
runtime/              日志、截图、演示输出
```

## 测试

```powershell
scripts\test.ps1
```

或：

```powershell
$env:PYTHONPATH = ".deps;."
python -m unittest discover -s tests -v
```

覆盖几何、模板、颜色、数字、OCR 过滤、资源清单、状态机、模拟器进攻循环。

## 使用边界

- 脚本会真实消耗搜索金币、兵力和药水，先用小号验证。
- 游戏 UI 更新会导致模板失效。
- 数字模板按当前中文版字体生成，换语言或字体需要重做。
- 自动化可能违反游戏服务条款，风险由使用者承担。

## 后续计划

- 建筑升级、研究、训练任务
- 图形界面与实时识别框
- 多任务调度
- 更强的 OCR 与多分辨率适配
