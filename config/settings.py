"""
Application settings loaded from environment variables.
"""

import os


def get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return value


# LINE Bot
CHANNEL_SECRET = get_required("ChannelSecret")
CHANNEL_ACCESS_TOKEN = get_required("ChannelAccessToken")

# Vertex AI
GCP_PROJECT = get_required("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Model
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-2.5-flash")

# Session
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "30"))
MAX_HISTORY_LENGTH = int(os.getenv("MAX_HISTORY_LENGTH", "20"))

# Google Maps Platform
GOOGLE_MAPS_API_KEY = get_required("GOOGLE_MAPS_API_KEY")
