"""Unit tests for loader/tool_combo.py"""
import os
import pytest


def test_google_maps_api_key_required(monkeypatch):
    """GOOGLE_MAPS_API_KEY must be set or config raises."""
    import importlib
    import sys

    # Remove config module from cache to force fresh import
    if "config" in sys.modules:
        del sys.modules["config"]
    if "config.settings" in sys.modules:
        del sys.modules["config.settings"]

    # Delete the env var and set required ones to valid values
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.setenv("ChannelSecret", "x")
    monkeypatch.setenv("ChannelAccessToken", "x")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "x")

    # Now importing should raise EnvironmentError
    with pytest.raises(EnvironmentError, match="GOOGLE_MAPS_API_KEY"):
        import config.settings


from unittest.mock import patch, MagicMock


def test_call_places_api_returns_restaurants(monkeypatch):
    """_call_places_api parses Places API response into expected dict."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "places": [
            {
                "displayName": {"text": "老王熱炒"},
                "formattedAddress": "台北市信義區市民大道100號",
                "rating": 4.6,
                "userRatingCount": 312,
                "reviews": [
                    {"text": {"text": "份量大、CP值高，朋友聚餐首選"}, "rating": 5},
                    {"text": {"text": "服務很快，菜色新鮮"}, "rating": 4},
                ],
            }
        ]
    }

    with patch("httpx.post", return_value=fake_response):
        from loader.tool_combo import _call_places_api
        result = _call_places_api(
            lat=25.0441, lng=121.5598,
            keyword="熱炒", min_rating=4.0, radius_m=1000,
        )

    assert "restaurants" in result
    assert len(result["restaurants"]) == 1
    r = result["restaurants"][0]
    assert r["name"] == "老王熱炒"
    assert r["rating"] == 4.6
    assert r["address"] == "台北市信義區市民大道100號"
    assert len(r["reviews"]) == 2
    assert "份量大" in r["reviews"][0]
