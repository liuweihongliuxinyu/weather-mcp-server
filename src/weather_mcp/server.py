"""
Weather MCP Server

一个最小化但完整的 MCP (Model Context Protocol) 服务端实现。
通过 wttr.in 免费 API 提供实时天气数据，无需 API Key。

MCP 协议要点（本节要学会的）：
1. Server 生命周期：initialize → tools/list → tools/call
2. JSON-RPC 2.0 传输：stdio transport（通过标准输入输出通信）
3. Tool 定义三要素：name（标识符）、description（AI 用来匹配意图）、inputSchema（参数约束）

运行方式：
    uv run python -m weather_mcp.server
    或
    pip install -e . && weather-mcp

接入 Claude Code（settings.json）：
    {
      "mcpServers": {
        "weather": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/weather-mcp-server", "weather-mcp"]
        }
      }
    }
"""

import logging
from typing import Any

import httpx
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

# ── 日志配置 ─────────────────────────────────────────────
# MCP 通过 stderr 输出日志，stdout 留给 JSON-RPC 消息
logging.basicConfig(
    level=logging.INFO,
    format="[WeatherMCP] %(levelname)s %(message)s",
    stream=__import__("sys").stderr,
)
logger = logging.getLogger("weather-mcp")

# ── 常量 ─────────────────────────────────────────────────
WTTR_BASE = "https://wttr.in"
USER_AGENT = "WeatherMCP/0.1.0 (github.com/AI_Marster/weather-mcp-server)"

# ── 工具实现层（纯业务逻辑，与 MCP 协议解耦）────────────────


async def fetch_weather(city: str, format_str: str = "j1") -> dict[str, Any] | str:
    """从 wttr.in 拉取天气数据。

    Args:
        city: 城市名（支持中文，如 "北京"、"Tokyo"、"London"）
        format_str: wttr.in 格式参数
            - "j1": JSON（含当前天气 + 3 天预报）
            - "j2": JSON（含当前天气 + 6 天预报 + 天文信息）
            - "3": 纯文本 3 天预报
            - "%t": 仅温度

    架构要点：
        这个函数是纯 HTTP 调用，不知道 MCP 的存在。
        分层设计让天气获取逻辑可以被其他协议（REST/gRPC）复用。
    """
    url = f"{WTTR_BASE}/{city}"
    params: dict[str, str] = {"format": format_str}
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()

        if format_str.startswith("j"):
            return response.json()
        return response.text


def format_current_weather(data: dict[str, Any], city: str) -> str:
    """将 wttr.in JSON 格式化为可读的当前天气报告。

    wttr.in JSON 结构（current_condition 段）：
        - temp_C / temp_F: 温度
        - FeelsLikeC / FeelsLikeF: 体感温度
        - weatherDesc[0].value: 天气描述（如 "Partly cloudy"）
        - windspeedKmph / winddir16Point: 风速/风向
        - humidity: 湿度百分比
        - visibility: 能见度（km）
        - pressure: 气压（hPa）
        - uvIndex: 紫外线指数
    """
    try:
        current = data["current_condition"][0]
        return f"""
📍 {city} 当前天气
━━━━━━━━━━━━━━━━━━━━━━━
🌡  温度:     {current['temp_C']}°C（体感 {current['FeelsLikeC']}°C）
☁️  天气:     {current['weatherDesc'][0]['value']}
💨 风速:     {current['windspeedKmph']} km/h {current['winddir16Point']}
💧 湿度:     {current['humidity']}%
👁  能见度:   {current['visibility']} km
🔆 紫外线:   {current['uvIndex']}
🔵 气压:     {current['pressure']} hPa
""".strip()
    except (KeyError, IndexError) as e:
        logger.warning("Failed to parse weather data: %s", e)
        return f"无法解析 {city} 的天气数据，请检查城市名是否正确"


def format_forecast(data: dict[str, Any], city: str, days: int = 3) -> str:
    """将 wttr.in JSON 格式化为 N 日天气预报。"""
    try:
        forecasts = data["weather"][:days]
        lines = [f"📍 {city} 未来 {days} 天预报", "━━━━━━━━━━━━━━━━━━━━━━━"]
        for day in forecasts:
            date = day["date"]
            high = day["maxtempC"]
            low = day["mintempC"]
            desc = day["hourly"][4]["weatherDesc"][0]["value"]  # 中午时段
            lines.append(f"📅 {date}  {low}°C ~ {high}°C  {desc}")
        return "\n".join(lines)
    except (KeyError, IndexError) as e:
        logger.warning("Failed to parse forecast data: %s", e)
        return "无法解析预报数据"


# ── 空气质量（Lab 1 新增：城市名 → 坐标 → AQI）────────────────

GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
AIR_QUALITY_API = "https://air-quality-api.open-meteo.com/v1/air-quality"


async def geocode_city(city: str) -> dict[str, float] | None:
    """城市名 → 经纬度坐标。

    Open-Meteo Geocoding API，免费无 Key。
    返回 {"lat": 39.9, "lon": 116.4} 或 None。
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GEOCODING_API,
            params={"name": city, "count": 1, "language": "zh"},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        return {"lat": results[0]["latitude"], "lon": results[0]["longitude"]}


async def fetch_air_quality(lat: float, lon: float) -> dict:
    """获取指定坐标的空气质量数据。

    返回指标：欧洲 AQI、PM2.5、PM10、NO₂、SO₂、O₃。
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            AIR_QUALITY_API,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "european_aqi,pm2_5,pm10,nitrogen_dioxide,sulphur_dioxide,ozone",
            },
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json()


def format_air_quality(data: dict, city: str) -> str:
    """将 Open-Meteo 空气质量数据格式化为可读报告。

    欧洲 AQI 级别：
        0-20  好 · 20-40  中等 · 40-60  对敏感人群不健康
        60-80 不健康 · 80-100 非常不健康 · >100 危险
    """
    try:
        current = data["current"]
        aqi = current["european_aqi"]

        if aqi <= 20:
            level = "🟢 好"
        elif aqi <= 40:
            level = "🟡 中等"
        elif aqi <= 60:
            level = "🟠 对敏感人群不健康"
        elif aqi <= 80:
            level = "🔴 不健康"
        elif aqi <= 100:
            level = "🟣 非常不健康"
        else:
            level = "⛔ 危险"

        return f"""
📍 {city} 空气质量
━━━━━━━━━━━━━━━━━━━━━━━
📊 AQI (欧洲):  {aqi} — {level}
🫁 PM2.5:       {current['pm2_5']} μg/m³
🧱 PM10:        {current['pm10']} μg/m³
💨 NO₂:         {current['nitrogen_dioxide']} μg/m³
🏭 SO₂:         {current['sulphur_dioxide']} μg/m³
☀️  O₃:          {current['ozone']} μg/m³
""".strip()
    except (KeyError, IndexError) as e:
        logger.warning("Failed to parse air quality data: %s", e)
        return f"无法解析 {city} 的空气质量数据"


# ── MCP 协议层（与业务逻辑对接）────────────────────────────


async def handle_list_tools() -> list[types.Tool]:
    """MCP 协议方法: tools/list

    当 AI 想知道"这个服务器能干什么"时调用此方法。
    返回 Tool 列表，每个 Tool 的 description 会被 AI 用来匹配用户意图。

    设计要点：
        - description 要包含关键词（weather/天气/温度），AI 通过语义匹配找到对应工具
        - inputSchema 定义参数约束，AI 自动从用户输入中提取参数值
        - 如果一个工具需要 API key，在 description 中说明
    """
    return [
            types.Tool(
                name="get_current_weather",
                title="获取当前天气",  # 人类可读标题
                description="查询一个城市的实时天气，包括温度、体感温度、天气描述、风速、湿度、能见度、紫外线指数、气压。支持中文城市名（如 '北京'）和英文城市名（如 'Tokyo'）。不需要 API Key。",
                inputSchema={
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，支持中文和英文。例如：北京、Shanghai、Tokyo、London、New York",
                        }
                    },
                },
            ),
            types.Tool(
                name="get_forecast",
                title="获取天气预报",
                description="查询一个城市未来几天的天气预报，包括每日最高/最低温度和天气描述。支持中文和英文城市名。",
                inputSchema={
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，支持中文和英文",
                        },
                        "days": {
                            "type": "integer",
                            "description": "预报天数（1-3），默认为 3",
                            "default": 3,
                            "minimum": 1,
                            "maximum": 3,
                        },
                    },
                },
            ),
            # ── Lab 1 新增：空气质量工具 ──
            types.Tool(
                name="get_air_quality",
                title="查询空气质量",
                description="查询一个城市的空气质量指数（AQI），包括 PM2.5、PM10、NO₂、SO₂、O₃ 等污染物浓度。支持中文和英文城市名。不需要 API Key。",
                inputSchema={
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称，支持中文和英文。例如：北京、Shanghai、Tokyo",
                        }
                    },
                },
            ),
        ]


async def handle_call_tool(
    name: str,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """MCP 协议方法: tools/call

    当 AI 决定调用某个工具时触发。params.name 为工具名，params.arguments 为用户提供的参数。

    设计要点：
        - 错误处理要返回 CallToolResult(is_error=True)，不要抛异常
        - 返回 TextContent 列表，AI 直接读取 text 字段
    """
    try:
        if name == "get_current_weather":
            city = arguments.get("city", "")
            if not city:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="❌ 请提供城市名称")],
                    is_error=True,
                )
            data = await fetch_weather(city, format_str="j1")
            if isinstance(data, dict):
                text = format_current_weather(data, city)
            else:
                text = data
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)]
            )

        elif name == "get_forecast":
            city = arguments.get("city", "")
            days = min(int(arguments.get("days", 3)), 3)
            if not city:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="❌ 请提供城市名称")],
                    is_error=True,
                )
            data = await fetch_weather(city, format_str="j1")
            if isinstance(data, dict):
                text = format_forecast(data, city, days)
            else:
                text = data
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)]
            )

        elif name == "get_air_quality":
            city = arguments.get("city", "")
            if not city:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="❌ 请提供城市名称")],
                    is_error=True,
                )
            # Step 1: 城市名 → 坐标
            coords = await geocode_city(city)
            if coords is None:
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text=f"❌ 找不到城市: {city}")],
                    is_error=True,
                )
            # Step 2: 坐标 → 空气质量
            data = await fetch_air_quality(coords["lat"], coords["lon"])
            text = format_air_quality(data, city)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=text)]
            )

        else:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text", text=f"❌ 未知工具: {name}"
                    )
                ],
                is_error=True,
            )

    except httpx.HTTPError as e:
        logger.error("HTTP error for tool '%s': %s", name, e)
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"❌ 获取天气失败: 网络请求出错（{e}）。请检查城市名是否正确。",
                )
            ],
            is_error=True,
        )
    except Exception as e:
        logger.exception("Unexpected error for tool '%s'", name)
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=f"❌ 服务器内部错误: {e}")
            ],
            is_error=True,
        )


# ── Resource 原语（Lab 2：让 AI 能"读"数据）─────────────────

SUPPORTED_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "杭州", "武汉",
    "Tokyo", "London", "New York", "Paris", "Berlin", "Sydney",
]


async def handle_list_resources() -> list[types.Resource]:
    """MCP 协议方法: resources/list

    与 tools/list 的区别：
    - Tool = AI 可以"做"什么（动词：查询、发送、创建）
    - Resource = AI 可以"读"什么（名词：文件、数据库记录、API 数据）

    这里把"支持的城市列表"暴露为 Resource。
    """
    return [
        types.Resource(
            uri="weather://cities",
            name="支持的城市",
            description="Weather MCP Server 支持查询天气的城市列表。包含中国主要城市和国际城市。",
            mimeType="application/json",
        )
    ]


async def handle_read_resource(uri: str) -> str:
    """MCP 协议方法: resources/read

    当 AI 读取某个 resource 的 URI 时触发。
    返回该 resource 的内容。

    与 tools/call 的区别：
    - tools/call → 执行动作（副作用）
    - resources/read → 读取数据（无副作用，幂等）
    """
    if uri == "weather://cities":
        import json
        return json.dumps(SUPPORTED_CITIES, ensure_ascii=False, indent=2)
    return f"未知资源: {uri}"


# ── Prompt 原语（Lab 2：预置提示词模板）─────────────────────


async def handle_list_prompts() -> list[types.Prompt]:
    """MCP 协议方法: prompts/list

    Prompt = 预定义的提示词模板，引导 AI 以特定方式完成任务。
    比 Tool 更高层：Tool 给 AI 能力，Prompt 给 AI 思路。

    这里提供一个"天气报告"模板。
    """
    return [
        types.Prompt(
            name="weather-report",
            description="生成指定城市的天气报告摘要，包含当前天气、预报和出行建议",
            arguments=[
                types.PromptArgument(
                    name="city",
                    description="城市名称",
                    required=True,
                ),
                types.PromptArgument(
                    name="style",
                    description="报告风格：brief（简洁）、detailed（详细）、travel（出行建议）",
                    required=False,
                ),
            ],
        )
    ]


async def handle_get_prompt(
    name: str, arguments: dict | None
) -> types.GetPromptResult:
    """MCP 协议方法: prompts/get

    返回填充参数后的提示词消息列表。
    这个消息会被注入到 AI 的上下文中，引导 AI 完成任务。
    """
    if name == "weather-report":
        args = arguments or {}
        city = args.get("city", "北京")
        style = args.get("style", "brief")

        prompts = {
            "brief": f"请查询 {city} 的当前天气，用 2-3 句话简要描述。",
            "detailed": f"请查询 {city} 的当前天气和未来 3 天预报，给出详细的天气分析，包括温度变化趋势、降水概率、风速等。",
            "travel": f"请查询 {city} 的当前天气、预报和空气质量，并基于天气情况给出出行建议（是否需要带伞、穿衣建议、是否适合户外活动）。",
        }

        return types.GetPromptResult(
            messages=[
                types.PromptMessage(
                    role="user",
                    content=types.TextContent(
                        type="text",
                        text=prompts.get(style, prompts["brief"]),
                    ),
                )
            ]
        )
    return types.GetPromptResult(
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(
                    type="text", text=f"未知提示词: {name}"
                ),
            )
        ]
    )


# ── Server 实例化与启动 ────────────────────────────────────


def create_server() -> Server:
    """创建并配置 MCP Server 实例。

    使用装饰器模式注册 Tool 处理器。
    MCP 运行时会在收到对应协议消息时自动调用这些回调。

    MCP 生命周期：
    1. 客户端发送 initialize 请求 → Server 自动处理
    2. 客户端发送 tools/list 请求 → 调用 handle_list_tools
    3. 客户端发送 tools/call 请求 → 调用 handle_call_tool（可多次）
    4. 会话结束 → Server 自动清理
    """
    server = Server(
        name="weather",
        version="0.1.0",
    )
    server.list_tools()(handle_list_tools)
    server.call_tool()(handle_call_tool)
    server.list_resources()(handle_list_resources)
    server.read_resource()(handle_read_resource)
    server.list_prompts()(handle_list_prompts)
    server.get_prompt()(handle_get_prompt)
    return server


async def run_server():
    """启动 stdio MCP Server。

    stdio_server() 打开标准输入/输出流，
    Server.run() 监听传入的 JSON-RPC 消息直到流关闭。
    """
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        logger.info("🌤  Weather MCP Server started (stdio transport)")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """CLI 入口点。

    anyio.run() 是 MCP SDK 的异步运行器，兼容 asyncio 和 trio。
    """
    import anyio

    anyio.run(run_server)


if __name__ == "__main__":
    main()
