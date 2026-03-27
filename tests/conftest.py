"""Pytest configuration for linebot-spot-finder tests."""
import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up environment variables for tests."""
    os.environ.setdefault("ChannelSecret", "test-channel-secret")
    os.environ.setdefault("ChannelAccessToken", "test-channel-access-token")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
    os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-maps-api-key")
