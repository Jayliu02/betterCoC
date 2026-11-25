# Vision Studio 使用说明

Vision Studio 是 betterCoC 的只读视觉调试界面：看画面、看识别结果、框选模板、试阈值、回放会话。
它不发送触控、按键或应用重启指令，也不会修改正式资源。

## 安装

GUI 是可选依赖，CLI 不装 Qt 也能用：

```powershell
pip install -e ".[studio]"
```

未安装 PySide6 时执行 `bettercoc studio` 会提示安装命令并以退出码 2 结束，其他子命令不受影响。

## 启动

```powershell
bettercoc --config config/mumu.yaml studio
bettercoc studio --source tests/fixtures/baseline
bettercoc studio --source runtime/diagnostics/sessions/<run_id>
```

| 参数 | 说明 |
| --- | --- |
| `--source` | 固定测试集目录或录制会话目录；省略时用 `tests/fixtures/baseline` |
| `--fixtures` | 阈值试验与误检/漏检统计使用的固定测试集 |
| `--workspace` | 草稿、导出事件、窗口截图的工作目录，默认 `runtime/studio` |
| `--screenshot PATH` | 渲染主窗口到 PNG 后退出，用于无显示环境或回归检查 |
| `--offscreen` | 使用 Qt offscreen 平台，不弹窗 |

无设备、无显示器也能启动：

```powershell
bettercoc studio --source tests/fixtures/baseline --screenshot runtime/studio/main.png --offscreen
```

## 页面

| 页面 | 用途 |
| --- | --- |
| Vision | 原始/归一化画面、识别项列表、匹配框、状态、得分、阈值、耗时；勾选“只看失败/未知”排查问题 |
| Template | 框选区域、模板预览、ROI 输入、阈值试验、草稿导出 |
| Replay | 加载录制会话，逐帧看事件，复现识别并列出与录制结果的差异 |
| Logs | 按事件类型/关键字过滤，导出诊断事件 JSONL |
| Settings | 只读显示版本、配置、资源清单、canonical 尺寸、后端 |

状态语义直接来自运行时：

- `matched`：有视觉证据（模板/颜色/数字/OCR 命中，或 point 颜色校验通过）。
- `coordinate_only`：`type: point` 没有 `check`，只代表“点了固定坐标”，不是识别成功。
- `miss`：未命中。
- `unknown`：识别无法执行（例如模板文件缺失、数字无法解析）。

## 画布

- 画面按宽高比等比缩放，多余空间留白，不拉伸。
- 滚轮缩放，按 `0` 回到适配视图。
- 鼠标悬停时状态栏显示 canonical 坐标；框选后右侧显示 canonical 矩形与宽高。
- 框选坐标从窗口像素换算到 1920x1080 canonical，再用于裁剪模板；误差不超过 1 个 canonical 像素
  （见 `tests/test_studio.py` 的四种画布情况）。

## 模板编辑流程

1. Vision 页面选一帧，切到 Template。
2. 在画布上拖拽框选按钮/图标区域。
3. 填写识别项名称；需要限制搜索区域时填 ROI（`x,y,w,h`）。
4. 调阈值，点“在固定测试集试验阈值”。表格给出每个阈值的应有命中、漏检、误检、正确排除、未标注命中。
5. 选合适阈值（界面会给出误检+漏检最少的建议值），点“导出草稿资源”。

导出只写 `runtime/studio/drafts/<名称>/`：

```text
drafts/<名称>/
  templates/<名称>.png   模板图
  <名称>.yaml            可直接合并的 assets.yaml 片段
  README.md              阈值、灰度、来源说明
```

草稿不会覆盖 `assets/assets.yaml` 或 `assets/templates`。确认无误后再人工复制，属于刻意设计。

## 回放流程

1. 先录制会话：`bettercoc record --frames 8` 或 `bettercoc record --live --frames 5`。
2. Replay 页面选择会话目录并加载。
3. 用“上一帧/下一帧”定位，事件表只显示当前帧的事件。
4. 点“复现识别并对比”，显示对比数量、不一致数量、资源指纹是否变化。

回放只读会话目录里的 PNG，不创建截图后端，也不连接 ADB。

## 只读边界

- Studio 不包含任何 `tap`/`swipe`/`keyevent`/`force-stop` 调用路径，`tests/test_studio.py` 会扫描源码断言这一点。
- “连接设备只读预览”只用 `exec-out screencap -p`；采集在后台 worker 里执行，主线程只负责显示。
- 设备断开时只显示“设备不可用”，不会尝试重连或自动操作。

## 已知限制

- 10 分钟连续运行未实测；已做队列上限与关闭释放测试，以及 offscreen 渲染回归。
- 只验证了 offscreen 渲染，未在真实多显示器/高 DPI 环境验证；缩放与留白是逻辑坐标，不依赖 DPI。
- 模板编辑只导出草稿，不提供一键合并到正式资源。
- 实时预览没有实现拖动画面（只支持滚轮缩放与复位）。
- 事件日志只在录制/回放会话里有内容；任务运行时不会自动产生事件（见 Stage 2 报告）。
