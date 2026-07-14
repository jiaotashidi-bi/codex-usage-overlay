# Codex Usage Overlay / Codex 余量浮窗

[中文](#中文) · [English](#english)

A compact Windows overlay that follows a Codex desktop pet and reports the current Codex plan usage window.

一个跟随 Codex 桌面宠物的 Windows 迷你浮窗，用来显示当前 Codex 套餐余量与重置时间。

---

## 中文

### 功能

- 读取当前 Codex 账号的套餐类型、已用比例、剩余比例和重置时间。
- 自动识别 Codex 宠物浮窗并跟随移动。
- 宠物隐藏时同步隐藏，再次唤醒时自动显示。
- 透明、置顶、可拖动；拖动后保存相对宠物的位置。
- 低余量时用颜色和简短文案直接提醒。
- 默认每 60 秒刷新，同时监听 Codex 限额更新通知。
- 不读取浏览器 Cookie，也不复制或保存 Codex 登录令牌。

### 环境要求

- Windows 10 或 Windows 11
- 已安装并登录 Codex CLI
- 支持宠物功能的 ChatGPT/Codex 桌面应用
- Python 3.10 或更高版本，并包含 Tkinter

先在终端确认：

```powershell
codex --version
python --version
```

### 安装与启动

```powershell
git clone https://github.com/jiaotashidi-bi/codex-usage-overlay.git
cd codex-usage-overlay
python main.py
```

Windows 用户也可以直接双击：

- `start-overlay.cmd`
- `启动-xiexie余量.cmd`

### 操作

- 双击浮窗：立即刷新。
- 按住左键拖动：调整相对宠物的位置并保存。
- 右键：刷新、重置跟随位置、切换置顶或退出。
- 右上角 `×`：退出。

### 自检与测试

读取一次真实限额并输出 JSON：

```powershell
python main.py --once
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

日志和窗口位置保存在：

```text
%LOCALAPPDATA%\xiexie-usage-overlay
```

### 实现说明与限制

限额数据来自本机 `codex app-server` 的 `account/rateLimits/read`，程序会监听 `account/rateLimits/updated` 并提供轮询回退。Codex App Server 目前属于实验性接口，未来 Codex 大版本升级后可能需要适配。

Codex 自定义宠物本身没有运行代码或绘制文字的扩展点，因此余量界面是独立透明窗口。宠物跟随依赖 Windows 上 Codex 宠物工具窗口的可见性和窗口特征；如果 Codex 更换窗口结构，识别规则也可能需要更新。

---

## English

### Features

- Reads the current Codex plan type, used percentage, remaining percentage, and reset time.
- Detects the Codex pet window and follows it as it moves.
- Hides when the pet is tucked away and reappears when the pet wakes up.
- Transparent, always-on-top, and draggable with a saved pet-relative offset.
- Uses color and concise messages to warn when usage is running low.
- Refreshes every 60 seconds and listens for Codex rate-limit update notifications.
- Does not read browser cookies or copy/store Codex authentication tokens.

### Requirements

- Windows 10 or Windows 11
- Codex CLI installed and signed in
- ChatGPT/Codex desktop app with Pets support
- Python 3.10+ with Tkinter

Verify the tools first:

```powershell
codex --version
python --version
```

### Install and run

```powershell
git clone https://github.com/jiaotashidi-bi/codex-usage-overlay.git
cd codex-usage-overlay
python main.py
```

On Windows, you can also double-click either launcher:

- `start-overlay.cmd`
- `启动-xiexie余量.cmd`

### Controls

- Double-click the overlay to refresh immediately.
- Drag with the left mouse button to save a new pet-relative position.
- Right-click to refresh, reset the follow position, toggle always-on-top, or quit.
- Click `×` to quit.

### Diagnostics and tests

Read the live rate limit once and print JSON:

```powershell
python main.py --once
```

Run the test suite:

```powershell
python -m unittest discover -s tests -v
```

Logs and window settings are stored in:

```text
%LOCALAPPDATA%\xiexie-usage-overlay
```

### Implementation notes and limitations

Usage data comes from the local `codex app-server` method `account/rateLimits/read`. The app listens for `account/rateLimits/updated` notifications and also polls as a fallback. Codex App Server is currently experimental, so future Codex releases may require compatibility updates.

Custom Codex pets do not provide a code or text-rendering extension point, so this project uses a separate transparent window. Pet following relies on the visibility and window characteristics of the Codex pet tool window on Windows; changes to the Codex window structure may require an updated detector.

