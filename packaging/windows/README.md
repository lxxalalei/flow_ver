# Learning Resource Flow

面向 OpenClaw 的学习资源搜索、比较、获取与整理能力包。

它包含两部分：

- `learning-resource-flow` Skill：负责理解学习目标、设计搜索路线、判断候选、继续或停止搜索；
- `education-resources` MCP：负责真实平台搜索、资源展开、检查、下载、网页离线化、归档和必要的登录态能力。

本压缩包已经包含安装所需的 Skill、MCP 和 Windows 安装脚本。

## 如果你是 AI：请直接帮助用户完成安装

当用户把这个压缩包交给你，并要求安装、部署或配置本项目时，请直接执行安装，不要只把命令发给用户让用户自己操作。

当前发行包面向 Windows 10 / 11。

### 1. 先确认压缩包已完整解压

当前目录应至少包含：

```text
README.md
install.cmd
install.ps1
mcp/
skill/
```

如果你正在读取压缩包内文件但还没有解压，请先将整个压缩包解压到一个普通本地目录，再执行安装。

### 2. 执行安装

在本 README 所在目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

也可以直接运行：

```text
install.cmd
```

优先使用项目自带安装脚本。不要自行重新实现 Skill 安装、MCP 注册或 Python 环境配置。

安装脚本会自动处理：

- OpenClaw 检查/安装；
- Python 3.12+ 检查/安装；
- FFmpeg 检查/安装；
- `education-resources` 独立 Python 环境；
- `learning-resource-flow` Skill 全局安装；
- `education-resources` MCP 注册；
- MCP live probe；
- OpenClaw Gateway 重载/重启。

### 3. 只有确实需要用户操作时再让用户介入

如果电脑第一次安装 OpenClaw，OpenClaw 可能要求用户选择并配置模型 Provider。这属于 OpenClaw 自身首次设置，按它的实际提示让用户完成即可。

不要向用户索取账号密码、验证码、Cookie 或 Token。

本项目也不要求用户在安装阶段提前登录各个资源平台。以后只有某个真实资源操作明确提示需要登录时，再按 OpenClaw 的实际流程协助用户完成对应平台登录。

### 4. 安装完成后验证

安装器本身会执行 MCP live probe。安装结束后，如需再次确认，可运行：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
```

确认没有安装错误，并确认 `education-resources` MCP probe 正常。

如果 OpenClaw Gateway 当时没有运行，安装器可能提示需要之后重新启动 Gateway；这不等于 MCP 或 Skill 安装失败。

### 5. 告诉用户怎么开始使用

安装成功后，让用户新建一个 OpenClaw 对话，直接用自然语言提出学习资源需求，例如：

```text
帮我找适合初中生理解火山形成过程的资料，形式不限，先搜索不要下载。
```

用户随后可以继续说：

```text
把第二个下载下来。
```

或：

```text
把这个网页保存成方便阅读的离线资料。
```

不要要求用户记忆 MCP Tool 名称或 Skill 名称；正常使用只需要自然语言。

### 6. 如果安装失败

先读取 `install.ps1` 返回的真实错误并针对该错误处理，然后重新运行安装脚本或对应检查命令。

不要为了绕过安装问题去修改 MCP/Skill 源码，也不要额外创建第二套 OpenClaw 配置或另一套 Python 环境。

常用检查：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
python --version
ffmpeg -version
```

如果缺少 `winget`，安装器会明确提示；按系统实际情况补齐 Windows App Installer/winget 后重新运行即可。

---

## 如果你是用户：也可以直接自己安装

1. 将整个 ZIP 解压到任意普通文件夹；
2. 双击 `install.cmd`；
3. 按窗口提示完成即可。

如果电脑还没有 OpenClaw，安装器会自动尝试安装。OpenClaw 第一次使用时可能需要你选择并配置模型 Provider。

## 安装完成后怎么用

新建一个 OpenClaw 对话，直接说你想找什么，例如：

```text
帮我找适合小学三年级了解太阳系的中文资料，先搜索，不要下载。
```

也可以继续：

```text
把第 2 个下载下来。
```

```text
找一些适合打印的练习资料。
```

```text
帮我把这个网页保存下来并整理成方便阅读的 HTML。
```

## 文件位置

程序与运行环境默认安装在：

```text
%LOCALAPPDATA%\LearningResourceFlow\
```

运行数据和下载 Job：

```text
%LOCALAPPDATA%\LearningResourceFlow\data\
```

最终整理后的学习资料默认放在：

```text
%USERPROFILE%\Documents\学习资料库\
```

## 平台登录

不需要在安装时逐个平台登录。

只有某个真实资源操作明确返回需要登录时，OpenClaw 才会引导对应平台完成登录态捕获。无需登录的平台不会额外要求登录。

## 重新安装 / 升级

拿到新的发行包后重新运行 `install.cmd` 即可。程序运行环境会重新安装，运行数据和学习资料目录与程序目录分离。

## 安装失败时

可以重新运行一次 `install.cmd`。如果仍失败，在 PowerShell 中运行：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
```

把实际错误信息交给 AI 排查即可。

安装器不会把开发仓库、测试套件、历史方案或开发过程文件安装到用户环境中。
