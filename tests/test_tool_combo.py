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
import httpx


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


def test_call_places_api_filters_low_rating(monkeypatch):
    """Restaurants below min_rating are excluded from results."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "places": [
            {
                "displayName": {"text": "低評價店"},
                "formattedAddress": "台北市",
                "rating": 3.2,
                "userRatingCount": 10,
                "reviews": [],
            },
            {
                "displayName": {"text": "好店"},
                "formattedAddress": "台北市信義區",
                "rating": 4.5,
                "userRatingCount": 200,
                "reviews": [],
            },
        ]
    }

    with patch("httpx.post", return_value=fake_response):
        from loader.tool_combo import _call_places_api
        result = _call_places_api(lat=25.0, lng=121.5, min_rating=4.0)

    assert len(result["restaurants"]) == 1
    assert result["restaurants"][0]["name"] == "好店"


def test_call_places_api_handles_http_error(monkeypatch):
    """HTTP errors return empty restaurants list with error key."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "bad-key")

    with patch("httpx.post", side_effect=httpx.HTTPError("connection failed")):
        from loader.tool_combo import _call_places_api
        result = _call_places_api(lat=25.0, lng=121.5)

    assert result["restaurants"] == []
    assert "error" in result


def test_execute_function_routes_correctly(monkeypatch):
    """_execute_function calls _call_places_api for search_nearby_restaurants."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")

    with patch("loader.tool_combo._call_places_api", return_value={"restaurants": []}) as mock_api:
        from loader.tool_combo import _execute_function
        result = _execute_function(
            "search_nearby_restaurants",
            {"keyword": "熱炒", "min_rating": 4.5, "radius_m": 500},
            lat=25.04, lng=121.56,
        )

    mock_api.assert_called_once_with(
        lat=25.04, lng=121.56,
        keyword="熱炒", min_rating=4.5, radius_m=500,
    )
    assert result == {"restaurants": []}


def test_execute_function_unknown_returns_error():
    """Unknown function name returns error dict."""
    from loader.tool_combo import _execute_function
    result = _execute_function("nonexistent_fn", {}, lat=0.0, lng=0.0)
    assert "error" in result
