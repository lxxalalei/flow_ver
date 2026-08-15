# Download Guidance

下载流程只回答一个业务问题：**用户已经明确选择这些资源，现在把它们下载下来。**

## 调用条件

只有用户已经明确表达“下载、获取、保存下来”等意图时，才调用：

```text
resource_download(resource_ids=[...], preferred_container="original")
```

用户说“第 1、3 个”“这两个”“全部”时，直接使用当前会话中对应候选的 `resource_id`。不创建 Presentation、Selection、Plan 或 confirmation token，也不重复询问已经明确的确认。

## 下载时发生什么

MCP 在实际执行每个资源前：

1. fresh Inspect 当前资源；
2. 根据实际 Representation 选择能处理它的下载器；
3. 启动异步 Job；
4. 通过 `resource_job_status(job_id)` 返回进度、文件和失败。

Provider 路由是实现细节。Agent 不指定 provider，不维护 provider version/digest，也不在失败后自行伪造 fallback。

## 格式

默认使用：

```text
preferred_container="original"
```

只有用户明确需要 PDF、MP4、MP3、HTML 等具体格式，而且该资源存在多个可下载表示时才指定格式。不要为了后端统一强制转格式。

## 结果解释

成功只依据 Job 返回的真实文件。关注：

- `status`
- `progress`
- `files[].filename/path/media_type/size_bytes`
- `failures[]`

没有文件就不能说下载成功。`AUTH_REQUIRED`、资源不可用、下载失败等按真实结果说明。

## 取消

用户要停止下载时：

```text
resource_job_cancel(job_id=...)
```

不需要 Flow 状态或取消事务链。
