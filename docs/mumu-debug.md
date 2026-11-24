# MuMu 实测记录

## 连接

MuMu 15 的 ADB：

```text
C:\Program Files\Netease\MuMu\nx_device\15.0\shell\adb.exe
```

设备串口：

```text
127.0.0.1:16384
```

`adb devices` 同时会看到 `emulator-5554` 和 `127.0.0.1:16384`，两者指向同一台设备。配置里使用后者，避免模拟器重启后 emulator 编号变化。

`bettercoc` 的 `AdbDevice.resolve()` 会自动执行 `adb connect`，因此每次 CLI 启动时不需要手动重连。

## 实测结果

| 项目 | 结果 |
| --- | --- |
| 截图 | 1920x1080，设备尺寸也是 1920x1080 |
| `home_attack` 实时识别 | 命中 0.999 |
| `attack_find_match` 实时识别 | 命中 1.000 |
| `wall_entry` 跨截图识别 | 命中 1.000 |
| `wall_more` / `wall_add_10` / `wall_confirm` | 命中 1.000 |
| `game_stop` 断线弹窗 | 命中 1.000，点击“重新载入游戏”后 7.7 秒回到主界面 |
| 批量选墙 +10/+1 | 不同背景下命中 0.968-0.997，单段和多段批量升级均通过 |
| 升墙按钮坐标 | 升级更多 925,753、+1 908,760、+10 710,755、金币 487,930、圣水 707,930、确定 1168,707，均已实机验证 |
| 关闭显示器 10 秒 | `screencap` 正常，连续帧有 10%-13% 像素变化 |
| 强制重进游戏 | 关闭开屏“欢迎回家”弹窗，19 秒回到主界面 |
| 真实自动战斗 | `prepare -> raid -> decide -> finish`，success，金币/圣水均增加 |
| 真实城墙升级 | 2 段金币 + 10 段圣水，资源减少与状态文件一致 |

截图里 `wm size` 报 `1080x1920`，这是竖屏自然尺寸。CoC 横屏渲染后 `screencap` 输出 1920x1080，归一化结果与 canonical 尺寸一致。

## 中文版 UI 对照

| 识别项 | 实际界面 |
| --- | --- |
| `home_attack` | 主城左下角金色“战斗”按钮 |
| `attack_find_match` | 战斗菜单左侧“常规战”卡片里的“搜索对手” |
| `build_button` | 主城右下角“建造” |
| `wall_entry` | 建筑和英雄列表里的城墙图标 |
| `wall_more` | 城墙面板“升级更多” |
| `wall_add_10` / `wall_add_1` | 批量选择加墙 |
| `wall_confirm` | 升级确认“确定” |

战斗菜单还有“排位战”和“练习模式”，当前配置默认走“常规战”。

城墙升级已改为“建造”入口，批量选择支持 +10/+1，金币或圣水余额足够即可升级。

## 操作时的界面行为

- 打开建筑或城墙面板后，点击面板外会选中其他建筑，主城 HUD 不响应
- 面板打开时按返回键会弹出“确定退出游戏？”对话框，取消后游戏不会退出
- 重新启动 CoC 会弹“欢迎回家”公告，需要先关闭后再识别主城
- 重进游戏后固定弹“欢迎回家”开屏面板，右上角红色 X 可关闭，`home_popup_close` 命中 1.000
- 长时间无操作会弹“还在吗？”断线弹窗，点“重新载入游戏”后回到主城
- 主城底部按钮和面板的位置在 1920x1080 下稳定，但选中建筑时镜头会轻微平移

因此 `prepare` 状态需要优先识别 `home_attack`，并在必要时用 `home_popup_close` 关闭欢迎弹窗，用 `side_panel_close` 关闭侧边面板。

## 已完成

- `home_attack`：主城“战斗”
- `attack_find_match`：搜索对手
- `army_attack`：军队确认页“进攻！”
- `scout_next`：下一个
- `auto_battle`：自动战斗
- `battle_return_home`：回营
- `game_stop`：断线弹窗“重新载入游戏”
- `home_popup_close`、`side_panel_close`
- `loot_gold` / `loot_elixir` / `loot_dark`：侦察资源数字
- `home_gold` / `home_elixir` / `home_dark`：主城资源数字
- `wall_cost_gold` / `wall_cost_elixir`：城墙单价
- `raid` 真实自动战斗，资源增加，成功回营
- `wall_upgrade` 2 段金币、10 段圣水批量升级，资源状态文件正常

## 未完成

- 手动下兵兜底模板：`scout_attack`、`battle_end`
- 多轮无人值守的压力测试
