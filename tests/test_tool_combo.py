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
