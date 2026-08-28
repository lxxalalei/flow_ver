# Learning Resource Flow

面向 OpenClaw 的学习资源搜索、比较、获取与整理能力包。

它包含两部分：

- `learning-resource-flow` Skill：负责理解学习目标、设计搜索路线、判断候选、继续或停止搜索；
- `education-resources` MCP：负责真实平台搜索、资源展开、检查、下载、网页离线化、归档和必要的登录态能力。

## 安装

1. 解压整个 ZIP 到任意文件夹；
2. 双击 `install.cmd`；
3. 按安装窗口提示完成即可。

如果电脑还没有 OpenClaw，安装器会调用 OpenClaw 官方 Windows 安装程序。OpenClaw 第一次安装时可能需要你选择并配置模型提供方，这是 OpenClaw 自身必须完成的首次设置。

安装器会自动处理：

- OpenClaw 检查/安装；
- Python 3.12+ 检查/安装；
- FFmpeg 检查/安装；
- `education-resources` 独立 Python 环境；
- CCTV 静态兼容解密运行包体检（不执行 npm 安装）；
- `learning-resource-flow` Skill 全局安装；
- `education-resources` MCP 注册；
- MCP live probe；
- OpenClaw Gateway 重载/重启。

安装完成后，新建一个 OpenClaw 对话即可使用，例如：

```text
帮我找适合初中生理解火山形成过程的资料，形式不限，先搜索不要下载。
```

后续可以直接继续：

```text
把第二个下载下来。
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

只有某个真实资源操作明确返回需要登录时，OpenClaw 才会引导对应平台完成登录态捕获。已经不需要登录的平台不会额外要求登录。

## 安装失败时

先重新运行一次 `install.cmd`。如果仍失败，可在 PowerShell 中检查：

```powershell
openclaw doctor
openclaw mcp doctor education-resources --probe
```

安装器不会把开发仓库、测试套件、历史方案或开发过程文件安装到用户环境中。
