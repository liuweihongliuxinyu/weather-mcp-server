"""Weather MCP Server 测试"""

import pytest
from weather_mcp.server import (
    create_server,
    format_current_weather,
    format_forecast,
    format_air_quality,
)


# ── 单元测试：格式化函数 ──────────────────────────────────

MOCK_DATA = {
    "current_condition": [
        {
            "temp_C": "22",
            "FeelsLikeC": "20",
            "weatherDesc": [{"value": "Partly cloudy"}],
            "windspeedKmph": "15",
            "winddir16Point": "NNE",
            "humidity": "65",
            "visibility": "10",
            "uvIndex": "5",
            "pressure": "1013",
        }
    ],
    "weather": [
        {
            "date": "2026-06-22",
            "maxtempC": "25",
            "mintempC": "18",
            "hourly": [{}] * 4 + [{"weatherDesc": [{"value": "Sunny"}]}],
        },
        {
            "date": "2026-06-23",
            "maxtempC": "23",
            "mintempC": "16",
            "hourly": [{}] * 4 + [{"weatherDesc": [{"value": "Light rain"}]}],
        },
        {
            "date": "2026-06-24",
            "maxtempC": "27",
            "mintempC": "19",
            "hourly": [{}] * 4 + [{"weatherDesc": [{"value": "Clear"}]}],
        },
    ],
}


def test_format_current_weather():
    result = format_current_weather(MOCK_DATA, "Beijing")
    assert "Beijing" in result
    assert "22°C" in result
    assert "20°C" in result  # 体感温度
    assert "Partly cloudy" in result
    assert "15" in result  # 风速
    assert "65%" in result  # 湿度


def test_format_forecast():
    result = format_forecast(MOCK_DATA, "Beijing", days=2)
    assert "Beijing" in result
    assert "25" in result
    assert "18" in result
    assert "Sunny" in result
    assert "2026-06-22" in result
    assert "2026-06-23" in result
    # 只请求了2天，第3天不应出现
    assert "2026-06-24" not in result


def test_format_current_weather_empty_data():
    """边界情况：空数据应返回友好错误信息而非崩溃"""
    result = format_current_weather({}, "Unknown")
    assert "无法解析" in result


def test_format_forecast_empty_data():
    """边界情况：空数据应返回友好错误信息而非崩溃"""
    result = format_forecast({}, "Unknown")
    assert "无法解析" in result


# ── 空气质量测试（Lab 1 新增）─────────────────────────────

MOCK_AQ_DATA = {
    "current": {
        "european_aqi": 35,
        "pm2_5": 12.5,
        "pm10": 25.0,
        "nitrogen_dioxide": 30.0,
        "sulphur_dioxide": 5.0,
        "ozone": 60.0,
    }
}


def test_format_air_quality():
    result = format_air_quality(MOCK_AQ_DATA, "Beijing")
    assert "Beijing" in result
    assert "35" in result
    assert "中等" in result  # AQI 35 对应"中等"
    assert "12.5" in result  # PM2.5
    assert "25.0" in result  # PM10


def test_format_air_quality_levels():
    """验证各 AQI 级别显示正确"""
    levels = [
        (10, "好"),
        (30, "中等"),
        (50, "对敏感人群不健康"),
        (70, "不健康"),
        (90, "非常不健康"),
        (120, "危险"),
    ]
    for aqi, expected_label in levels:
        data = {"current": {**MOCK_AQ_DATA["current"], "european_aqi": aqi}}
        result = format_air_quality(data, "Test")
        assert expected_label in result, f"AQI {aqi} 应显示 '{expected_label}'"


def test_format_air_quality_empty_data():
    """边界情况：空数据应返回友好错误信息"""
    result = format_air_quality({}, "Unknown")
    assert "无法解析" in result


# ── 集成测试：Server 实例 ──────────────────────────────────

@pytest.mark.asyncio
async def test_server_creation():
    """验证 Server 实例可以正常创建"""
    server = create_server()
    assert server.name == "weather"
    assert server.version == "0.1.0"


@pytest.mark.asyncio
async def test_list_tools():
    """验证 tools/list 返回了正确的工具列表"""
    from weather_mcp.server import handle_list_tools

    result = await handle_list_tools()
    tool_names = [t.name for t in result]
    assert "get_current_weather" in tool_names
    assert "get_forecast" in tool_names
    assert len(result) == 3  # weather + forecast + air_quality


@pytest.mark.asyncio
async def test_call_get_current_weather_missing_city():
    """验证工具调用时缺少必填参数的处理"""
    from weather_mcp.server import handle_call_tool

    result = await handle_call_tool("get_current_weather", {})
    assert result.is_error is True
    assert "请提供城市名称" in result.content[0].text


@pytest.mark.asyncio
async def test_call_get_air_quality_missing_city():
    """验证空气质量查询缺少城市名时的错误处理"""
    from weather_mcp.server import handle_call_tool

    result = await handle_call_tool("get_air_quality", {})
    assert result.is_error is True
    assert "请提供城市名称" in result.content[0].text


@pytest.mark.asyncio
async def test_tool_list_includes_air_quality():
    """验证 tools/list 包含新增的空气质量工具"""
    from weather_mcp.server import handle_list_tools

    result = await handle_list_tools()
    aq_tool = [t for t in result if t.name == "get_air_quality"]
    assert len(aq_tool) == 1
    assert "PM2.5" in aq_tool[0].description
