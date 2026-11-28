# 校准指南

首次运行前需要采集模板、确定坐标、配置资源清单。整个流程不修改游戏文件，只做截图和 ADB 输入。

## 1. 模拟器与 ADB

推荐 1920x1080 横屏。常见模拟器的 ADB 端口：

| 模拟器 | 常见端口 |
| --- | --- |
| MuMu Player 12 | 16384 |
| LDPlayer | 5555 |
| BlueStacks | 5555 |
| NoxPlayer | 62001 |

端口以模拟器实际设置为准。连接：

```powershell
adb connect 127.0.0.1:5555
adb devices
```

MuMu 15 的 ADB 路径通常是 `C:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe`，串口通常是 `127.0.0.1:16384`。betterCoC 会自动执行 `adb connect`，配置里只写 serial 即可。

看到 `device` 状态即可。把路径写进配置：

```yaml
device:
  adb_path: C:\platform-tools\adb.exe
  serial: 127.0.0.1:5555
```

验证输入：

```powershell
bettercoc capture -o runtime/shots/check.png
```

截图应正好是 1920x1080。如果模拟器是 1600x900，betterCoC 会归一化，模板仍然按 1920x1080 坐标裁剪。

## 2. 截图

```powershell
bettercoc capture -o runtime/shots/home.png
```

需要采集的界面：

1. 主城，带“战斗”按钮
2. 进攻菜单
3. “我的军队”确认页
4. 侦察界面，带左上角资源
5. 自动战斗/战斗界面
6. 战斗结算

每次切换界面后重新 `capture`。保持游戏语言、皮肤、分辨率不变。

## 3. 裁剪模板

用任意图片编辑器打开 1920x1080 截图，记下目标区域的 `x,y,w,h`。

```powershell
bettercoc assets add --name home_attack --rect 1600,850,300,220 --image runtime/shots/home.png
```

命令会：

- 裁剪并保存 `assets/templates/home_attack.png`
- 在 `assets/assets.yaml` 增加条目
- 打印建议的 ROI

一次会话可以连续添加：

```powershell
bettercoc assets add --name attack_find_match --rect 160,742,240,62 --image runtime/shots/attack.png
bettercoc assets add --name auto_battle --rect 1251,774,295,68 --color --image runtime/shots/scout.png
bettercoc assets add --name battle_return_home --rect 837,881,249,103 --color --image runtime/shots/result.png
```

`--color` 表示三通道匹配。颜色语义重要的按钮使用它，形状识别用默认灰度。

### 裁剪规则

- 只截稳定元素，避开资源数字、倒计时、玩家名
- 保留足够独特的形状，太小容易误匹配
- 不要截整块带渐变的背景
- 同一按钮在不同界面出现时，优先截最独特的局部
- 游戏语言变化后重新截

### 阈值

默认 0.86。调整建议：

| 场景 | 阈值 |
| --- | --- |
| 固定 UI、清晰模板 | 0.88 到 0.95 |
| 有轻微动画/压缩噪声 | 0.80 到 0.88 |
| 半透明、缩放 | 0.72 到 0.82 |

先跑 `probe` 看实际分数，再决定阈值。低于 0.7 的模板通常需要重新裁剪。

### ROI

模板可能出现在多个位置时，加 ROI 限制搜索范围，减少误匹配并加速：

```yaml
assets:
  home_attack:
    file: home_attack.png
    roi: [1450, 780, 470, 300]
```

`assets add` 不会自动写入 ROI，需要手动加到清单。ROI 必须大于模板尺寸。

### 遮罩

透明 PNG 默认使用 Alpha 遮罩。需要忽略模板背景色时：

```yaml
assets:
  auto_battle:
    file: auto_battle.png
    grayscale: false
    mask_color: [30, 30, 30]
    mask_tolerance: 12
```

`mask_color` 是 BGR。带遮罩时匹配方法会自动从 `ccoeff_normed` 切换到 `ccorr_normed`。

## 4. 固定坐标按钮

按钮位置固定时不要用模板，直接写 `type: point`：

```yaml
home_attack:
  type: point
  point: [110, 935]
```

坐标是 1920x1080 归一化画面上的点击位置。用截图工具量出按钮中心即可，模拟器分辨率不同会自动换算。

需要知道按钮在不在时，加 `check` 做小区域平均颜色校验：

```powershell
bettercoc sample --rect 60,1027,120,18 --image runtime/mumu/diag-now.png
```

把输出的 `BGR 均值` 填进 `check.color`，先给 `tolerance: 25`：

```yaml
home_attack:
  type: point
  point: [110, 935]
  check:
    roi: [60, 1027, 120, 18]
    color: [41, 157, 207]
    tolerance: 25
```

校准规则：

- `roi` 只取按钮内部颜色稳定的一小块，避开文字、图标和渐变边缘
- `tolerance` 越小越严格；先在目标界面 `probe` 确认命中，再在其它界面确认不命中
- 弹窗背景会整体变暗（约 50%），同一个按钮给两组颜色即可同时匹配正常和变暗状态：`color: [[96,91,249],[48,46,125]]`
- 换分辨率、语言或 UI 皮肤后重新采样
- 整排按钮会随状态移位时（侦察页的“自动战斗”），不要用固定坐标，保留模板 + 限定 `roi`

颜色条件不满足时 `find()` 返回未命中，`click()` 会继续等待。没有 `check` 的 point 永远命中，只适合“确定在某个界面后无条件点一下”的按钮。

## 5. 颜色项（可选）

颜色识别用于确认按钮是否可用，例如绿色/金色按钮检测。先采样：

```powershell
bettercoc sample --rect 560,860,330,100 --image runtime/shots/ui.png
```

输出示例：

```text
BGR 均值: (76.0, 175.0, 80.0)
HSV 中位数: (61.0, 145.0, 175.0)
建议 lower: [46, 95, 125]
建议 upper: [76, 195, 225]
```

写入清单：

```yaml
some_button_available:
  type: color
  space: hsv
  lower: [40, 90, 100]
  upper: [80, 255, 255]
  min_ratio: 0.25
```

`min_ratio` 是目标颜色像素占 ROI 的比例。当前 `raid` 和 `wall_upgrade` 都直接依赖模板和数字识别，不使用颜色项。

## 6. OCR

文本 OCR 用于配置了 `type: ocr` 的识别项。资源数量默认由数字模板读取，不需要 Tesseract。

1. 安装 Tesseract：`winget install UB-Mannheim.TesseractOCR`，或从 UB Mannheim 发布页安装
2. 安装 Python 包：`pip install -r requirements-ocr.txt`
3. 配置路径：

```yaml
vision:
  ocr:
    backend: tesseract
    lang: eng
    psm: 6
    tesseract_cmd: C:\Program Files\Tesseract-OCR\tesseract.exe
```

4. 给资源区域加 OCR 项：

```yaml
loot_gold:
  type: ocr
  roi: [40, 24, 240, 70]
  regex: '[0-9][0-9,.]*[KMBkmb万亿]?'
```

5. 验证：

```powershell
bettercoc recognize loot_gold --image runtime/shots/scout.png
```

如果识别不到，尝试：

- 增大 `upscale` 到 3
- 打开 `binarize`，白字深底时配合 `invert`
- 调整 ROI，只框数字
- 换 `psm`（单行用 7，单块用 6）

OCR 不可用时文本识别项不可用；资源数量由 `assets/digits` 数字模板读取，不受影响。

## 7. 数字模板

`raid` 用 `assets/digits` 读取侦察界面左上角的金币、圣水和暗黑，不依赖 Tesseract。

当前 ROI：

```text
loot_gold   [70, 125, 250, 50]
loot_elixir [70, 195, 250, 50]
loot_dark   [70, 265, 200, 50]
```

模板由 [tools/build_digits.py](../tools/build_digits.py) 从中文版侦察截图生成：

```powershell
python tools\build_digits.py --image runtime/mumu/scout.png --output assets\digits
```

脚本里的 ROI、示例数字需要按新截图调整。验证：

```powershell
bettercoc --config config/mumu.yaml probe --image runtime/mumu/scout.png
```

`loot_gold`、`loot_elixir`、`loot_dark` 应输出正确数字。数字 ROI 里出现图标时，识别器会按连通域的纵向位置剔除离群项。

## 8. 自动战斗

`raid` 默认点侦察界面的“自动战斗”，不需要手动下兵坐标。

```yaml
task:
  name: raid
  raid:
    auto_battle: true
    loot_check: true
    min_total: 1000000
    max_next: 15
```

手动兜底才需要配置：

```yaml
army:
  troop_slots:
    - [150, 980]
  deploy_points:
    - [760, 480]
  waves: 1
```

## 9. 城墙升级

城墙入口在“建造”面板里，不需要点地图上的墙：

1. 点击主城右下角“建造”
2. 在“建筑和英雄”列表上下滑动
3. 找到“城墙 xN”行，读取右侧可升级数量，点击
4. 点击“升级更多”进入批量选择
5. 用“+10 / +1”选数量
6. 金币/圣水按钮位置固定在 `[487,930]`、`[707,930]`
7. 确认页点“确定”

主城“建造”是固定坐标 `build_button`。城墙行优先用 `wall_row_label`（“城墙 x”文字）定位，城墙图标会随等级变化，`wall_entry` 只作为备用锚点。升墙数量/金币/圣水/确定按钮坐标在 `config/*.yaml` 的 `task.wall_upgrade` 里。使用文字锚点时数量 ROI 从文字右侧自动推算；使用图标锚点时用 `remaining_offset`。还需要 `home_gold/elixir/dark`、`wall_cost_gold/elixir` 的数字 ROI。

`wall_row_label` 会随分辨率/窗口大小变化。换分辨率后从实机截图裁一块“城墙 x”文字，宽高约 60x34（1920 规范坐标），放到 `assets/templates/wall_row_label.png`，阈值从 0.9 起调。

完整说明见 [wall-loop.md](wall-loop.md)。

## 10. 验证

### doctor

```powershell
bettercoc doctor
```

关注 `FAIL`。`WARN` 中的未校准项需要补齐。

### probe

```powershell
bettercoc probe --save runtime/probe.png
```

每一项都会打印命中框和分数。打开标注图确认框的位置正确。

只验证单项：

```powershell
bettercoc recognize home_attack attack_find_match auto_battle --image runtime/shots/home.png --save runtime/check.png
```

### dry-run

```powershell
bettercoc run --dry-run --max-cycles 1 --trace
```

确认：

- 状态转移符合预期
- 点击坐标落在正确位置
- 没有大量识别超时

### 正式运行

```powershell
bettercoc run --trace
```

先设置 `max_cycles: 1`，观察一轮完整流程。确认资源消耗、兵种部署、回主城都正常后，再增加轮数。

## 11. 常见问题

### 模板匹配分数很高但点错位置

模板太通用，例如纯色按钮、重复图标。加 ROI、换更独特的局部、提高阈值。

### 模板分数在 0.6 到 0.8 波动

背景有动画或透明度。重新裁剪，避开动态区域；或者降到 0.75 并加 ROI。

### 归一化后按钮变形

模拟器不是 16:9。改成 1920x1080 或 1280x720。4:3 需要额外适配。

### ADB 截图黑屏

模拟器使用 DirectX 渲染时，部分截图方式会黑屏。继续用 `adb exec-out screencap`；仍然失败时换模拟器渲染模式。

### Tesseract 中文识别差

安装 `chi_sim` 语言包，把 `lang` 改成 `chi_sim`，并缩小 ROI 到纯文本区域。

### 游戏更新后全部失效

重新采集模板。识别项名称和任务流程不变，只替换 PNG 和坐标。
