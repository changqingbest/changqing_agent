import json
import unittest

import httpx

from app.tools import create_default_registry


class NetworkToolTests(unittest.TestCase):
    def test_web_search_uses_keyless_bing_rss_and_limits_results(self) -> None:
        rss = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item><title>结果一</title><link>https://example.com/1</link>
            <description><![CDATA[<b>第一条</b> 摘要]]></description></item>
          <item><title>结果二</title><link>https://example.com/2</link>
            <description>第二条摘要</description></item>
        </channel></rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "www.bing.com")
            self.assertEqual(request.url.params["format"], "rss")
            return httpx.Response(200, text=rss, headers={"content-type": "text/xml"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            tools = create_default_registry(http_client=client)
            result = tools.call("web_search", {"query": "测试", "max_results": 1})

        self.assertEqual(result["provider"], "bing_rss")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["snippet"], "第一条 摘要")

    def test_web_search_uses_tavily_when_key_is_configured(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url, "https://api.tavily.com/search")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            body = json.loads(request.content)
            self.assertEqual(body["query"], "Python")
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Python",
                            "url": "https://python.org",
                            "content": "Official site",
                            "score": 0.9,
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            tools = create_default_registry(tavily_api_key="test-key", http_client=client)
            result = tools.call("web_search", {"query": "Python"})

        self.assertEqual(result["provider"], "tavily")
        self.assertEqual(result["results"][0]["url"], "https://python.org")

    def test_weather_geocodes_location_and_normalizes_forecast(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "geocoding-api.open-meteo.com":
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "name": "北京",
                                "admin1": "北京市",
                                "country": "中国",
                                "latitude": 39.9,
                                "longitude": 116.4,
                                "timezone": "Asia/Shanghai",
                            }
                        ]
                    },
                )
            self.assertEqual(request.url.host, "api.open-meteo.com")
            self.assertEqual(request.url.params["forecast_days"], "1")
            return httpx.Response(
                200,
                json={
                    "timezone": "Asia/Shanghai",
                    "current": {
                        "time": "2026-08-17T10:00",
                        "temperature_2m": 30.0,
                        "weather_code": 1,
                    },
                    "current_units": {"temperature_2m": "°C"},
                    "daily": {
                        "time": ["2026-08-17"],
                        "weather_code": [61],
                        "temperature_2m_max": [31.0],
                        "temperature_2m_min": [22.0],
                        "precipitation_sum": [2.0],
                        "precipitation_probability_max": [70],
                        "sunrise": ["2026-08-17T05:30"],
                        "sunset": ["2026-08-17T19:05"],
                    },
                    "daily_units": {"temperature_2m_max": "°C"},
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            tools = create_default_registry(http_client=client)
            result = tools.call("get_weather", {"location": "北京", "days": 1})

        self.assertEqual(result["location"]["name"], "北京")
        self.assertEqual(result["current"]["weather"], "大部晴朗")
        self.assertEqual(result["daily"][0]["weather"], "小雨")
        self.assertEqual(result["provider"], "open-meteo")

    def test_network_tool_arguments_are_validated(self) -> None:
        tools = create_default_registry()
        with self.assertRaisesRegex(ValueError, "1 到 10"):
            tools.call("web_search", {"query": "x", "max_results": 11})
        with self.assertRaisesRegex(ValueError, "1 到 7"):
            tools.call("get_weather", {"location": "北京", "days": 8})


if __name__ == "__main__":
    unittest.main()
