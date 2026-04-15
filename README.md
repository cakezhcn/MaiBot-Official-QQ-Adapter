# MaiBot Official QQ Adapter

QQ 官方机器人适配器，为 [MaiBot](https://github.com/Mai-with-u/MaiBot) 提供 QQ 官方平台支持。

本项目基于官方 [qq-botpy](https://github.com/tencent-connect/botpy) 库实现，使用 [maim_message](https://github.com/MaiM-with-u/maim_message) 协议与 MaiBot 通信。

## 架构概述

```
QQ 官方平台
    │  WebSocket (by qq-botpy)
    ▼
QQOfficialBotAdapter (botpy.Client)
    │  maim_message WebSocket
    ▼
MaiBot (localhost:8080)
```

1. **qq-botpy** 负责 QQ 官方 WebSocket 连接（心跳、重连、Token 刷新均自动处理）。  
2. **maim_message.MessageClient** 通过 WebSocket 与 MaiBot 双向通信。  
3. 收到 QQ 消息后转换为 maim_message 格式转发给 MaiBot；收到 MaiBot 回复后发回 QQ。

## 支持的消息类型

| 事件 | 描述 |
|------|------|
| `on_at_message_create` | 频道 @ 消息（公域机器人） |
| `on_group_at_message_create` | 群 @ 消息 |
| `on_c2c_message_create` | C2C 私聊消息 |
| `on_direct_message_create` | 频道私信 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
cp config/config_example.toml config/config.toml
```

编辑 `config/config.toml`，填写：

```toml
[qq]
app_id     = "你的 App ID"
app_secret = "你的 App Secret"

[qq.intents]
public_guild_messages = true   # 频道 @ 消息
public_messages       = true   # 群 / C2C 消息
direct_message        = true   # 频道私信
guild_messages        = false  # 私域全量消息（需私域权限）

[maibot]
server_url = "ws://localhost:8080/ws"   # MaiBot 的 maim_message 服务地址
token      = ""                         # 可选认证 Token
```

> **注意**：`server_url` 对应 MaiBot 配置中的 `HOST`/`PORT`（默认 `ws://localhost:8080/ws`）。

### 3. 运行

确保 MaiBot 已启动，然后：

```bash
python main.py
```

也可以通过环境变量指定配置文件路径：

```bash
QQ_ADAPTER_CONFIG=/path/to/config.toml python main.py
```

## 文件结构

```
MaiBot-Official-QQ-Adapter/
├── main.py                        # 入口
├── pyproject.toml                 # 项目元数据
├── requirements.txt               # 依赖列表
├── config/
│   ├── config_example.toml        # 配置示例
│   └── config.toml                # 实际配置（自行创建）
└── adapter/
    ├── __init__.py
    ├── qq_adapter.py              # botpy.Client 子类，处理 QQ 事件
    ├── maibot_client.py           # maim_message.MessageClient 封装
    └── message_converter.py       # QQ 消息 ↔ maim_message 格式转换
```

## 依赖

| 包 | 用途 |
|----|------|
| `qq-botpy` | QQ 官方机器人 SDK，处理 WebSocket 连接 |
| `maim-message` | MaiBot 消息协议库 |
| `aiohttp` | 异步 HTTP（maim-message 依赖） |
| `toml` | 配置文件解析 |

## Docker

```bash
docker build -t maibot-qq-adapter .
docker run -v $(pwd)/config:/app/config maibot-qq-adapter
```

## 常见问题

**Q: 机器人收不到消息？**  
A: 检查 `[qq.intents]` 配置，确认开启了对应的事件类型。公域机器人使用 `public_guild_messages`，群机器人使用 `public_messages`。

**Q: MaiBot 连接失败？**  
A: 确认 MaiBot 已启动并监听在 `server_url` 指定的地址。检查防火墙设置。

**Q: 如何开启调试日志？**  
A: 在配置文件中设置 `[logging] level = "DEBUG"`。

