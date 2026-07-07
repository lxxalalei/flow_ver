# 平台搜索错误

搜索错误统一包含：

```json
{
  "platform": "generic",
  "query": "四年级数学公开课程",
  "error_code": "NETWORK_TIMEOUT",
  "message": "平台搜索超时",
  "retryable": true
}
```

常用错误：

| 错误码 | 含义 | 可重试 |
|---|---|:---:|
| `SEARCH_PLATFORM_UNAVAILABLE` | 平台未注册或不可执行 | 否 |
| `SYSTEM_ADAPTER_LOAD_FAILED` | adapter 缺失或接口错误 | 否 |
| `SYSTEM_TOOL_NOT_FOUND` | 平台脚本不存在 | 否 |
| `SYSTEM_DEPENDENCY_MISSING` | 缺少平台搜索所需的 Python 依赖 | 否，先补运行环境 |
| `NETWORK_TIMEOUT` | 请求超时 | 是 |
| `SEARCH_BLOCKED` | 验证码、风控或搜索引擎访问拦截 | 是，更换会话或延迟后 |
| `AUTH_REQUIRED` | 缺少当前平台要求的登录信息 | 否，模型读取平台文档并协助配置 |
| `SEARCH_EXECUTION_FAILED` | 搜索脚本执行失败 | 视原因 |
| `PARSE_EMPTY_CONTENT` | 没有可解析响应 | 否 |
| `PARSE_FORMAT_NOT_SUPPORTED` | 响应格式无法解析 | 否 |

单次有限重试由 adapter 处理。执行器只负责超时隔离，不叠加多轮重试。依赖和必需认证在联网前检查。错误对象不得包含 Cookie、token、完整请求头或浏览器认证数据。

向用户处理认证错误时，由模型读取对应平台文档，说明缺少的具体登录信息并询问是否需要协助配置。配置完成后重新运行当前平台搜索；不要把认证失败解释为平台没有结果。
