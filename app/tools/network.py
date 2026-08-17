from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from app.tools.registry import Tool


_USER_AGENT = "ChangqingAgent/0.3 (+local AI agent)"
_TIMEOUT = httpx.Timeout(12.0, connect=5.0)

# Open-Meteo 使用 WMO weather interpretation codes。先在工具层翻译成中文，
# 模型无需记忆数字含义，也能直接组织自然语言回答。
_WEATHER_CODES = {
    0: "晴朗",
    1: "大部晴朗",
    2: "局部多云",
    3: "阴天",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "强毛毛雨",
    56: "轻微冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "轻微冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "米雪",
    80: "小阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _request(
    method: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """统一执行外部 HTTP 请求，并把网络错误转换为适合模型理解的异常。"""
    headers = {"User-Agent": _USER_AGENT, **kwargs.pop("headers", {})}
    try:
        if client is not None:
            response = client.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
        else:
            with httpx.Client(follow_redirects=True) as temporary_client:
                response = temporary_client.request(
                    method, url, headers=headers, timeout=_TIMEOUT, **kwargs
                )
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        raise RuntimeError("外部服务请求超时，请稍后重试。") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise RuntimeError(f"外部服务返回 HTTP {status}。") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"外部服务请求失败：{exc}") from exc


def _plain_text(value: str) -> str:
    """清理 RSS 摘要中的少量 HTML 标签，避免把标签噪音交给模型。"""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split())


def _web_search(
    query: str,
    max_results: int = 5,
    *,
    tavily_api_key: str = "",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("搜索关键词不能为空。")
    if not 1 <= max_results <= 10:
        raise ValueError("max_results 必须在 1 到 10 之间。")

    # 配置 Tavily 后优先走面向 Agent 的结构化搜索接口；未配置时使用免密钥的
    # Bing RSS 搜索，保证本地首次启动也具备基本联网检索能力。
    if tavily_api_key:
        response = _request(
            "POST",
            "https://api.tavily.com/search",
            client=client,
            headers={"Authorization": f"Bearer {tavily_api_key}"},
            json={
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            },
        )
        payload = response.json()
        results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
                "score": item.get("score"),
            }
            for item in payload.get("results", [])[:max_results]
        ]
        provider = "tavily"
    else:
        response = _request(
            "GET",
            "https://www.bing.com/search",
            client=client,
            params={"q": query, "format": "rss", "count": max_results},
        )
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise RuntimeError("搜索服务返回了无法解析的结果。") from exc
        results = []
        for item in root.findall("./channel/item")[:max_results]:
            results.append(
                {
                    "title": _plain_text(item.findtext("title", "")),
                    "url": item.findtext("link", ""),
                    "snippet": _plain_text(item.findtext("description", "")),
                    "published_at": item.findtext("pubDate") or None,
                }
            )
        provider = "bing_rss"

    return {"query": query, "provider": provider, "results": results}


def _get_weather(
    location: str,
    days: int = 3,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    location = location.strip()
    if len(location) < 2:
        raise ValueError("地点名称至少需要 2 个字符。")
    if not 1 <= days <= 7:
        raise ValueError("days 必须在 1 到 7 之间。")

    geocoding = _request(
        "GET",
        "https://geocoding-api.open-meteo.com/v1/search",
        client=client,
        params={"name": location, "count": 1, "language": "zh", "format": "json"},
    ).json()
    matches = geocoding.get("results") or []
    if not matches:
        raise ValueError(f"未找到地点：{location}")
    place = matches[0]

    forecast = _request(
        "GET",
        "https://api.open-meteo.com/v1/forecast",
        client=client,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": "auto",
            "forecast_days": days,
            "current": (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "precipitation,weather_code,wind_speed_10m"
            ),
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,precipitation_probability_max,sunrise,sunset"
            ),
        },
    ).json()

    current = dict(forecast.get("current") or {})
    current["weather"] = _WEATHER_CODES.get(current.get("weather_code"), "未知")
    daily = forecast.get("daily") or {}
    dates = daily.get("time") or []
    daily_rows = []
    for index, date in enumerate(dates):
        code = daily.get("weather_code", [None] * len(dates))[index]
        daily_rows.append(
            {
                "date": date,
                "weather": _WEATHER_CODES.get(code, "未知"),
                "temperature_max": daily.get("temperature_2m_max", [None] * len(dates))[index],
                "temperature_min": daily.get("temperature_2m_min", [None] * len(dates))[index],
                "precipitation_sum": daily.get("precipitation_sum", [None] * len(dates))[index],
                "precipitation_probability_max": daily.get(
                    "precipitation_probability_max", [None] * len(dates)
                )[index],
                "sunrise": daily.get("sunrise", [None] * len(dates))[index],
                "sunset": daily.get("sunset", [None] * len(dates))[index],
            }
        )

    return {
        "location": {
            "name": place.get("name"),
            "admin1": place.get("admin1"),
            "country": place.get("country"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "timezone": forecast.get("timezone") or place.get("timezone"),
        },
        "current": current,
        "current_units": forecast.get("current_units", {}),
        "daily": daily_rows,
        "daily_units": forecast.get("daily_units", {}),
        "provider": "open-meteo",
    }


def create_network_tools(
    *, tavily_api_key: str = "", client: httpx.Client | None = None
) -> list[Tool]:
    """创建搜索和天气工具；client 参数仅用于测试或自定义网络传输。"""
    return [
        Tool(
            name="web_search",
            description="搜索互联网获取最新资料，返回标题、链接和摘要。需要时应引用结果 URL。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要搜索的具体问题或关键词"},
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda query, max_results=5: _web_search(
                query,
                max_results,
                tavily_api_key=tavily_api_key,
                client=client,
            ),
        ),
        Tool(
            name="get_weather",
            description="按城市或地区名称查询当前天气和未来 1 至 7 天预报。",
            parameters={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市或地区，如 北京、深圳"},
                    "days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 7,
                        "default": 3,
                    },
                },
                "required": ["location"],
                "additionalProperties": False,
            },
            handler=lambda location, days=3: _get_weather(location, days, client=client),
        ),
    ]
