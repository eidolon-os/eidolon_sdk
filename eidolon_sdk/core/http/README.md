# HTTP 客户端规范

SDK 的 `core.http` 是已有 SDK 依赖的 Python 服务的 HTTPX 创建入口。
它只负责传输配置；路由、权限、业务协议、服务发现和模型用量仍属于各自项目。

## 标准做法

HTTPX 的 Client 自带连接池。复用 Client 才能复用 TCP/TLS；HTTP/1.1 也支持
keep-alive。HTTP/2 提供多路复用，是按上游能力和测量结果选择的优化，不是所有
调用的前提。启用 `http2=True` 仍需服务器协商，不能假定实际使用了 HTTP/2。

官方依据：[Clients](https://www.python-httpx.org/advanced/clients/)、
[Async](https://www.python-httpx.org/async/)、
[HTTP/2](https://www.python-httpx.org/http2/)。

## 代码与生命周期

```python
from eidolon_sdk.core.http import HTTPClientSettings, create_async_client

# composition/lifespan 创建；同一服务生命周期内复用；退出时关闭。
async with create_async_client(
    HTTPClientSettings(timeout_seconds=5, connect_timeout_seconds=2, trust_env=False),
) as http:
    await run_service(http)  # 业务适配器借用，不关闭 http
```

- 创建方关闭；通过构造函数注入的客户端由上层关闭。
- 服务热路径复用服务级池，语音会话复用会话级池；禁止每轮重复建池。
- 有限的 CLI、启动探测、独立工具操作可以用一次性 async context，确保关闭。
- 不跨 event loop 共享。不同 TLS、代理、UDS、认证隔离要求使用不同客户端；
  请求令牌放在每次请求中，不能写入共享池的全局可变 headers。
- 内部控制面沿用 `trust_env=False`；外部服务保留自己的代理策略。
- `create_async_client` 接受 HTTPX 原生参数覆盖，无须再包一套 HTTP 协议。
- 默认 HTTP/1.1；池默认上限 100 / keepalive 20 / 空闲 5 秒。
  SDK 超时默认 30 秒、连接 5 秒；调用方按原有预算显式覆盖。
- Agent LLM 显式启用 HTTP/2、空闲保留 60 秒，并由 Agent 声明
  `httpx[http2]` 依赖。SDK 不要求所有服务安装或启用 HTTP/2。

## 超时、重试与流

- HTTPX timeout 是连接、读、写、连接池等待的阶段预算，不是请求总时限。
  业务需要总时限时由上层 `asyncio.timeout` 约束，保留取消传播。
- `ServiceHTTPClient._request(timeout=None)` 继承客户端超时；不能把默认
  None 传给 HTTPX 而意外禁用超时。刻意无限等待须显式 `httpx.Timeout(None)`。
- 默认单次尝试。现有 `HTTPRetryPolicy` 仅按显式策略对安全方法重试。
  设备写入、LLM 生成、决策 POST 不在传输工厂自动重放。
- streaming 使用 `async with client.stream(...)`；退出、错误、取消都关闭响应。
  响应结束后保留客户端池，服务退出时才关闭池。
- 阶段诊断复用 HTTPX/httpcore trace（连接/TLS/响应头等）；业务适配器记录
  首个有效输出、完成、用量、请求 ID、失败/取消。LLM token 用量不能移入通用
  HTTP 层；日志不记录凭据或完整对话。统计必须区分传输耗时与模型生成耗时。

## 2026-09-29 项目审查范围

| 项目 | 处理及边界 |
| --- | --- |
| SDK | 扩展现有工厂的池/H2 配置，修复默认超时继承；复用原重试策略 |
| Agent | 全部运行时 HTTPX 构造接入工厂；家居、参与决策、Memory 发现及 Laya 适配器复用拥有者的池；LLM 保留已有共享连接桥接和阶段统计 |
| Channel | HTTPX 构造统一；家居 Hub 客户端复用服务池；语音轮次复用会话池；保留总时限 |
| Hub | 现有 AsyncExitStack 管理的池使用统一工厂 |
| Kernel | 设备、Companion、目录和就绪探测使用工厂；保持注入/拥有责任 |
| Admin | 现有服务级池及 UDS/TCP 隔离保留，构造使用统一工厂 |
| Memory | 独立构建契约禁止依赖 eidolon SDK；保留原生 HTTPX 长生命周期 embedder 和有限探测 context，遵守同一生命周期规则 |
| Data / Ops / Models | 本次未发现需迁移的业务运行时 HTTPX 构造；训练、部署、基准脚本保持操作级生命周期 |
| LiveKit / STT / TTS / Avatar | 框架管理的 aiohttp、WebSocket 连接保持其自身生命周期，不套 HTTPX |
| Mobile / Web | Dart 注入客户端、证书约束和浏览器连接池由各平台管理，不引入 Python SDK |

本次不新增全局连接池注册表、重试中间件或通用遥测框架。
连接配置的统一不改变 Device 执行权威、Laya/LLM 分工或模型训练边界。

### 验证记录

- SDK HTTP：11 passed；超时继承/覆盖、关闭责任、POST 丢失回执不重放。
- Agent：448 passed；覆盖 LLM、Memory 发现、家居、参与决策、解释层、
  Admin 语义流、运行时、工具及架构边界。退出后出现 Loguru sink 关闭日志。
- Channel：450 passed；覆盖家居能力、Channel provider、语音传输/空闲/启动。
- Hub：61 passed / 1 skipped；Kernel：43 passed / 1 skipped。
- Admin：129 passed / 3 failed。三个失败均为设备准入测试要求固定三个 scope，
  而原有 HEAD 的 `local_api/device_admissions.py` 已含另外两个 control scope；
  本次对此文件仅替换客户端创建入口，没有改权限列表，未调整权限断言。
- Memory 独立性边界：3 passed。Memory 源码未改。
- 本次没有新增线上性能结果或发布；已有 HTTP/2 测量在 Agent 的
  `docs/reviews/2026-09-29-home-llm-latency/`，不据此宣称多轮长尾全部解决。
