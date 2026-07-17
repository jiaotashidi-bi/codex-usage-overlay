# Codex Usage Overlay / Codex 余量浮窗

[中文](#中文) · [English](#english)

A transparent Windows overlay that follows the currently selected Codex desktop pet and shows live Codex plan usage.

一个跟随当前 Codex 桌面宠物的透明 Windows 浮窗，用来显示套餐余量、进度和重置倒计时。

---

## 中文

### 功能

- 通过本机 `codex app-server` 读取当前 Codex 账号的套餐余量。
- 自动读取 `~/.codex/config.toml` 中的 `selected-avatar-id`。
- 自定义宠物会继续读取 `~/.codex/pets/<id>/pet.json` 中的 `displayName`，无需手动输入宠物名称。
- 用户切换宠物后，浮窗标题会自动更新。
- 跟随宠物移动；宠物隐藏时浮窗同步隐藏，宠物出现时自动恢复。
- 根据宠物所在显示器的 DPI 自动调整大小，支持多显示器切换。
- 提供自动、小、中、大和自定义尺寸模式。
- 支持一档额度、两档额度和 Credits，窗口高度会自动调整。
- 默认每 60 秒刷新，同时监听 `account/rateLimits/updated` 通知。
- 支持开机启动、保持置顶、拖动微调、低额度提醒和立即刷新。
- 不读取浏览器 Cookie，不复制或保存 Codex 登录令牌。

### 环境要求

- Windows 10 或 Windows 11
- Python 3.10 或更新版本，并包含 Tkinter
- 已安装并登录 Codex CLI
- 支持 Pets 的 Codex/ChatGPT 桌面应用

先确认：

```powershell
codex --version
python --version
```

如果 Codex CLI 尚未登录：

```powershell
codex.cmd login
```

### 推荐安装

```powershell
git clone https://github.com/jiaotashidi-bi/codex-usage-overlay.git
cd codex-usage-overlay
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

`setup.ps1` 会：

- 检查 Python 和 Codex CLI 余量接口；
- 创建当前用户的隐藏开机启动脚本；
- 启动浮窗；
- 不询问宠物名称，名称完全从 Codex 当前选择中自动识别。

只安装但不开机启动：

```powershell
.\setup.ps1 -NoStartup
```

只配置但暂不启动：

```powershell
.\setup.ps1 -NoLaunch
```

也可以直接运行：

```powershell
python main.py
```

或双击：

- `start-overlay.cmd`
- `启动-Codex余量.cmd`

### 自动宠物名称

选择自定义宠物时，Codex 通常会写入：

```toml
selected-avatar-id = "custom:my-pet"
```

浮窗随后读取：

```text
~/.codex/pets/my-pet/pet.json
```

并使用其中的 `displayName`。如果清单缺失，则使用安全的宠物 ID；如果当前 Codex 版本没有提供可识别的选择，则显示通用名称 `Codex`。没有手动宠物名称设置。

### DPI 自动适配

当前设计以 200% 显示缩放为参考（下表为近似像素尺寸，可能有 1 像素取整差异）：

| 状态 | 100% | 125% | 150% | 200% |
|---|---:|---:|---:|---:|
| 单额度 | 129×75 | 161×94 | 194×113 | 258×150 |
| 双额度 | 129×115 | 161×144 | 194×173 | 258×230 |
| 带 Credits | 129×125 | 161×156 | 194×188 | 258×250 |

实际尺寸还会乘以用户在设置中选择的小、中、大或自定义比例。

### 操作

- 双击浮窗：立即刷新。
- 左键拖动：保存相对宠物的位置偏移。
- 右键：打开设置、切换置顶、重置跟随位置或退出。
- 设置中可调整：尺寸模式、自定义比例、刷新间隔、提醒阈值和开机启动。

### 命令行

读取一次真实余量：

```powershell
python main.py --once
```

双额度演示：

```powershell
python main.py --demo
```

安装或删除开机启动：

```powershell
python main.py --install-startup
python main.py --uninstall-startup
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

配置和日志保存在：

```text
%LOCALAPPDATA%\codex-usage-overlay
```

旧版 `%LOCALAPPDATA%\xiexie-usage-overlay` 设置和旧启动项会在首次运行 v0.4.0 时自动迁移。

### 实现说明

余量来自本机 Codex App Server 的 `account/rateLimits/read`。程序监听 `account/rateLimits/updated` 并使用轮询作为回退。宠物名称和选择来自 Codex 本地配置；这些字段属于当前 Codex 桌面实现，未来版本变化时可能需要兼容更新。

---

## English

### Features

- Reads plan usage through the local `codex app-server`.
- Detects the selected pet from `~/.codex/config.toml` and custom `pet.json` metadata.
- Updates the visible pet name automatically when the selected pet changes; no manual name setting exists.
- Follows the pet and mirrors its visible/hidden state.
- Scales against the DPI of the pet's current monitor and updates across monitors.
- Provides Auto, Small, Medium, Large, and Custom size modes.
- Supports one usage window, two usage windows, and optional Credits with dynamic heights.
- Polls every 60 seconds by default and listens for rate-limit update notifications.
- Supports per-user startup, always-on-top behavior, drag offsets, warnings, and manual refresh.
- Does not read browser cookies or store Codex authentication tokens.

### Requirements

- Windows 10 or Windows 11
- Python 3.10+ with Tkinter
- Codex CLI installed and signed in
- Codex/ChatGPT desktop app with Pets support

### Recommended setup

```powershell
git clone https://github.com/jiaotashidi-bi/codex-usage-overlay.git
cd codex-usage-overlay
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

The setup script validates Python and Codex access, installs a hidden per-user startup launcher, and starts the overlay. It never asks for a pet name.

Options:

```powershell
.\setup.ps1 -NoStartup
.\setup.ps1 -NoLaunch
```

Manual launch:

```powershell
python main.py
```

You can also double-click `start-overlay.cmd` or `启动-Codex余量.cmd`.

### Automatic pet identity

For `selected-avatar-id = "custom:my-pet"`, the overlay reads `~/.codex/pets/my-pet/pet.json` and uses `displayName`. A safe pet ID or `Codex` is used when metadata is unavailable. Pet selection is checked periodically so switching pets updates the overlay without a restart.

### Controls

- Double-click: refresh now.
- Drag: save a pet-relative offset.
- Right-click: open settings, toggle topmost, reset position, or quit.
- Settings: size mode, custom scale, refresh interval, warning threshold, and startup.

### Commands

```powershell
python main.py --once
python main.py --demo
python main.py --install-startup
python main.py --uninstall-startup
python -m unittest discover -s tests -v
```

Configuration and logs are stored in `%LOCALAPPDATA%\codex-usage-overlay`. Legacy v0.3 settings and startup entries are migrated automatically.

### Implementation note

Usage data comes from `account/rateLimits/read`; `account/rateLimits/updated` notifications are used with polling fallback. Pet selection metadata is local to the current Codex desktop implementation and may require compatibility updates after future Codex releases.
