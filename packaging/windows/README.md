# Learning Resource Flow

面向 OpenClaw 的学习资源搜索、比较、获取与整理能力包。

它包含两部分：

- `learning-resource-flow` Skill：负责理解学习目标、设计搜索路线、判断候选、继续或停止搜索；
- `education-resources` MCP：负责真实平台搜索、资源展开、检查、下载、网页离线化、归档和必要的登录态能力。

本发行包已经包含安装所需的 Skill、MCP 和 Windows 安装脚本。

## 安装

当前发行包支持 **Windows 10 / 11**。

### 1. 完整解压发行包

目录中应至少包含：

```text
README.md
install.cmd
install.ps1
mcp/
skill/
```

不要直接在压缩包预览环境中运行安装脚本，先将整个发行包解压到普通本地目录。

### 2. 运行安装脚本

直接运行：

```text
install.cmd
```

或在 PowerShell 中运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

安装应通过项目自带脚本完成，无需手工重新配置 Skill、MCP 或 Python 环境。

安装脚本会自动处理：

- OpenClaw 检查与安装；
- Python 3.12+ 检查与安装；
- FFmpeg 检查与安装；
- `education-resources` 独立 Python 环境；
- 抖音合集展开所需的 Chromium 浏览器（下载失败不阻塞安装，该能力会显式提示缺少依赖）；
- `learning-resource-flow` Skill 全局安装；
- `education-resources` MCP 注册；
- MCP live probe；
- OpenClaw Gateway 重载或重启。

### 3. 完成 OpenClaw 首次设置

如果电脑第一次安装 OpenClaw，OpenClaw 可能要求选择并配置模型 Provider。按 OpenClaw 自身提示完成即可。

资源平台不需要在安装阶段逐个登录。只有后续真实资源操作明确要求登录时，才需要完成对应平台的登录态捕获。

账号密码、验证码、Cookie 或 Token 不需要写入本项目配置文件。

### 4. 验证安装

安装器本身会执行 MCP live probe。需要再次检查时，可运行：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
```

确认 `education-resources` MCP probe 正常即可。

如果 OpenClaw Gateway 当时没有运行，安装器可能提示之后重新启动 Gateway；这不代表 MCP 或 Skill 安装失败。

## 开始使用

安装完成后，新建一个 OpenClaw 对话，直接描述需要的学习资源。

例如：

```text
帮我找适合初中生理解火山形成过程的资料，形式不限，先搜索不要下载。
```

继续选择已有候选：

```text
把第二个下载下来。
```

保存网页：

```text
把这个网页保存成方便阅读的离线资料。
```

查找练习资料：

```text
找一些适合打印的练习资料。
```

正常使用只需要自然语言，不需要记忆 Skill 名称或 MCP Tool 名称。

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

平台登录按需进行，不是固定前置步骤。

只有某个真实资源操作明确返回需要登录时，OpenClaw 才进入对应平台的登录态流程。无需登录的平台不会额外要求登录。

## 重新安装与升级

拿到新的发行包后，完整解压并重新运行：

```text
install.cmd
```

程序运行环境会重新安装。运行数据和学习资料目录与程序目录分离，不需要手工迁移普通下载资料。

## 安装失败

先根据 `install.ps1` 返回的真实错误处理，不要通过修改 MCP 或 Skill 源码绕过安装问题。

常用检查命令：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
python --version
ffmpeg -version
```

如果缺少 `winget`，安装器会明确提示。补齐 Windows App Installer / winget 后重新运行安装即可。

安装器只安装运行所需文件，不会把开发仓库、测试套件、历史方案或开发过程文件安装到用户环境中。
