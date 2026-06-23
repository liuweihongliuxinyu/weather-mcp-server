# 🌤 Weather MCP Server

> 一个最小化但完整的 MCP (Model Context Protocol) 服务端实现，为 AI Agent 提供实时天气查询能力。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-1.x-green.svg)](https://modelcontextprotocol.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 为什么做这个项目

这是 **从零学 AI Agent 架构** 的实战项目 #1。MCP 协议是 AI Agent 与外部世界交互的标准接口——理解 MCP 是理解整个 Agent 架构的第一步。本项目用最小的代码量（~200 行）展示 MCP Server 的完整生命周期。

## 快速开始

```bash
# 1. 安装
cd weather-mcp-server
pip install -e .

# 2. 测试
pytest tests/ -v

# 3. 运行（stdio transport）
weather-mcp
```

## 接入 Claude Code

在 `claude_desktop_config.json` 或 `.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "weather": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "D:\\AI_Space\\ClaudeCode-DeepSeek\\weather-mcp-server",
        "weather-mcp"
      ]
    }
  }
}
```

重启 Claude Code 后，你就能看到 `mcp__weather__get_current_weather` 和 `mcp__weather__get_forecast` 两个工具。

## 提供的工具

| 工具名 | 用途 | 参数 |
|--------|------|------|
| `get_current_weather` | 实时天气（温度/体感/风速/湿度/紫外线） | `city` (string) |
| `get_forecast` | 未来 N 天预报 | `city` (string), `days` (int, 1-3) |

## 架构

```
┌──────────────────────────────────────────┐
│           Claude Code (Host)             │
│  ┌────────────────────────────────────┐  │
│  │   MCP Client (weather)             │  │
│  │   JSON-RPC over stdio              │  │
│  └──────────────┬─────────────────────┘  │
└─────────────────┼────────────────────────┘
                  │ stdin/stdout
┌─────────────────▼────────────────────────┐
│         Weather MCP Server               │
│  ┌────────────────────────────────────┐  │
│  │  handle_list_tools()              │  │
│  │  handle_call_tool()               │  │
│  └──────────┬─────────────────────────┘  │
│             │                            │
│  ┌──────────▼─────────────────────────┐  │
│  │  fetch_weather() (wttr.in)        │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

## 项目结构

```
weather-mcp-server/
├── pyproject.toml          # 项目配置和依赖
├── README.md               # 本文件
├── src/
│   └── weather_mcp/
│       ├── __init__.py
│       └── server.py       # MCP Server 核心（~200行）
└── tests/
    └── test_server.py      # 单元测试 + 集成测试
```

## 学会了什么

通过这个项目你可以理解：

1. **MCP 协议三层模型**: Host → Client → Server
2. **JSON-RPC 2.0**: MCP 的底层传输格式
3. **stdio transport**: 进程间通过标准输入输出通信
4. **Tool 定义**: name + description + input_schema，AI 如何匹配工具
5. **业务逻辑与协议解耦**: fetch_weather() 不知道 MCP 的存在
6. **错误处理**: MCP 协议要求返回 is_error 而非抛异常

## License

MIT
