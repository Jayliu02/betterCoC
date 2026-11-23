# BetterGI 图像识别模型研究

本文记录搭建 betterCoC 前对 BetterGI 脚本识别 API 的梳理，以及哪些设计被沿用、哪些地方做了调整。

## 资料来源

- BetterGI 图像识别与 OCR：<https://www.bettergi.com/dev/js/rec.html>
- BetterGI 元素定位 BvLocator：<https://www.bettergi.com/dev/js/BvLocator.html>
- BetterGI 页面操作 BvPage：<https://www.bettergi.com/dev/js/BvPage.html>
- BetterGI 链式流程 BvFlow：<https://www.bettergi.com/dev/js/BvFlow.html>
- BetterGI 仓库：<https://github.com/babalae/better-genshin-impact>

## 识别分层

BetterGI 的脚本识别可以拆成四层。

### 1. 截图区域 ImageRegion

`captureGameRegion()` 返回 `ImageRegion`。游戏分辨率高于 1080P 时缩放到 1920x1080，不高于 1080P 时保留原尺寸。`ImageRegion` 同时是图像和区域：

- `srcMat`：OpenCV Mat
- `deriveCrop`：裁剪子区域
- `find` / `findMulti`：执行识别
- `click` / `clickTo`：把区域坐标换算成游戏窗口坐标并点击

脚本里大量使用 `1920x1080` 坐标，模板也按这个尺度截取。

### 2. 识别对象 RecognitionObject

识别对象是声明式配置，不直接执行识别。核心属性：

| 属性 | 作用 |
| --- | --- |
| `recognitionType` | 模板、OCR、颜色等 |
| `regionOfInterest` | 搜索区域 |
| `templateImageMat` | 模板图像 |
| `threshold` | 模板匹配阈值 |
| `use3Channels` | 三通道匹配 |
| `templateMatchMode` | OpenCV 模板匹配模式 |
| `lowerColor` / `upperColor` | 颜色范围 |
| `allContainMatchText` | OCR 必须包含全部文本 |
| `oneContainMatchText` | OCR 至少包含一个文本 |
| `regexMatchText` | OCR 正则过滤 |

工厂方法把常用组合固化：

- `RecognitionObject.templateMatch(mat)`
- `RecognitionObject.templateMatch(mat, useMask, maskColor)`
- `RecognitionObject.templateMatch(mat, x, y, width, height)`
- `RecognitionObject.ocr(x, y, width, height)`
- `RecognitionObject.ocrMatch(x, y, width, height, matchTexts)`

调用方通常只改 `threshold` 等少量参数。

### 3. 定位器 BvLocator

`BvLocator` 把“识别一次”提升为“等待元素出现”：

- `findAll()`：立即查找
- `isExist()`：是否存在
- `waitFor(timeout)`：超时抛异常
- `tryWaitFor(timeout)`：超时返回空
- `waitForDisappear(timeout)`
- `click()` / `clickIfExist()`
- `DefaultTimeout` 默认 10000ms
- `DefaultRetryInterval` 默认 250ms

内部逻辑是“截图 → 识别 → 未命中则等待重试”，脚本不需要手写轮询。

### 4. 页面与流程 BvPage / BvFlow

`BvPage` 提供截图、文本定位、OCR、点击：

```js
const page = new BvPage();
const regions = await page.getByText("确认").waitFor(5000);
regions.first().click();
```

`BvFlow` 把动作串起来，并支持“重复动作直到条件满足”：

```js
await page.flow()
  .keyPress("ESCAPE")
  .untilAnyText(["成", "就"], rect)
  .click()
  .untilText("天地万象")
  .click()
  .waitUntilText("达成成就")
  .run();
```

识别结果沿流程传递，后续无参 `click()` 使用最近一次命中的中心点。

## betterCoC 的映射

| BetterGI 概念 | betterCoC 对应实现 |
| --- | --- |
| `captureGameRegion` | `Context.screen()`，统一归一化到 1920x1080 |
| `ImageRegion` | `Screen`，保存图像、设备尺寸、Viewport |
| `RecognitionObject` | `Recognition` 数据类 + YAML 资源清单 |
| `templateMatch` | `Recognition(kind=TEMPLATE)` + `Vision.find` |
| `ocr` | `Recognition(kind=OCR)` + Tesseract 后端 |
| 颜色范围 | `Recognition(kind=COLOR)` + HSV/BGR 过滤 |
| `Region` 结果 | `Match(rect, score, text, name)` |
| `BvLocator` | `Context.wait` / `try_wait` / `wait_gone` / `click`，以及 `Locator` 链式封装 |
| `BvPage` | `Context` + `Vision` |
| `BvFlow` | `StateMachine` + 任务处理器 |
| `Recognition.json` | `assets/assets.yaml` |
| 1080P 坐标 | `vision.canonical_size` + `Viewport` |

## 设计取舍

### 归一化策略

BetterGI 只在高于 1080P 时缩放。betterCoC 始终归一化到配置的 `canonical_size`，默认 1920x1080。原因是模板和点击坐标必须共用同一套空间，模拟器分辨率变化时不用重新校准。代价是 4:3 画面会被横向拉伸，需要在 16:9 模拟器上校准。

### 资源清单

BetterGI 在 JS 里创建 `RecognitionObject`，代码和模板绑定。betterCoC 把识别项放进 `assets/assets.yaml`，任务只引用名称。这样可以：

- 只改配置完成校准，不改代码
- 同一个模板被多个任务复用
- `doctor` / `probe` 逐项检查
- 后续做图形化校准时直接读写清单

### 定位器语义

`BvLocator` 的默认超时和重试间隔很实用。betterCoC 把这些参数放到 `Context.wait` 的调用点，任务可以按界面不同设置不同超时。`Context.wait` 每次重试都会重新截图，避免使用过期画面。

### 流程编排

`BvFlow` 适合线性步骤。扫荡升墙需要循环、资源判断、失败恢复，`StateMachine` 更直接：状态处理器返回下一个状态，转移带耗时记录，异常统一转到 `recover`。

### 技术栈

BetterGI 使用 C# / WPF / OpenCvSharp。betterCoC 选择 Python，原因是 OpenCV、OCR、图像调试的迭代速度快，后续可以用 PySide6 或 Web 前端补界面。ADB 输入与截图足以覆盖模拟器场景。

## 对 BetterGI 的引用边界

本项目参考公开文档中的 API 设计和概念，没有复制 BetterGI 的源代码。模板、截图、任务流程均为本项目自行实现。BetterGI 面向原神，betterCoC 面向部落冲突，识别对象和任务逻辑没有复用价值。
