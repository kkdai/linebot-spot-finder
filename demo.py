"""
Demo script — 不需要 LINE Bot，直接測試兩個核心功能：
  1. Maps Grounding：用座標搜尋附近地點
  2. Gemini Chat：對話式問答 + Google Search grounding

使用方式：
  python demo.py maps        # 測試 Maps Grounding
  python demo.py chat        # 測試 Gemini Chat
  python demo.py all         # 全部測試（預設）

環境變數需求：
  GOOGLE_CLOUD_PROJECT=your-project-id
  GOOGLE_CLOUD_LOCATION=us-central1
"""

import asyncio
import sys

from google import genai
from google.genai import types

from loader.maps_grounding import search_nearby_places

# ── 設定 ──────────────────────────────────────────────────

import os
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gemini-2.5-flash")

# 市民大道 / 信義區附近
DEMO_LAT = 25.0441
DEMO_LNG = 121.5598

SEPARATOR = "─" * 50


# ── 1. Maps Grounding Demo ────────────────────────────────

async def demo_maps():
    print(f"\n{SEPARATOR}")
    print("Maps Grounding Demo")
    print(f"{SEPARATOR}")
    print(f"座標：{DEMO_LAT}, {DEMO_LNG}（市民大道附近）\n")

    cases = [
        ("restaurant", None),
        ("parking",    None),
        ("restaurant", "請找評價 4 顆星以上、適合多人聚餐的熱炒店，列出名稱和地址。"),
    ]

    for place_type, custom_query in cases:
        label = custom_query or f"預設查詢（{place_type}）"
        print(f"[查詢] {label}")
        result = await search_nearby_places(
            latitude=DEMO_LAT,
            longitude=DEMO_LNG,
            place_type=place_type,
            custom_query=custom_query,
        )
        print(result)
        print()


# ── 2. Gemini Chat Demo ───────────────────────────────────

def demo_chat():
    print(f"\n{SEPARATOR}")
    print("Gemini Chat Demo（含 Google Search Grounding）")
    print(f"{SEPARATOR}\n")

    if not GCP_PROJECT:
        print("❌ 請設定 GOOGLE_CLOUD_PROJECT 環境變數")
        return

    client = genai.Client(
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_LOCATION,
        http_options=types.HttpOptions(api_version="v1"),
    )

    chat = client.chats.create(
        model=CHAT_MODEL,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1024,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    questions = [
        "信義區市民大道附近有哪些值得推薦的熱炒餐廳？",
        "剛才提到的這些店，哪一間評價最高？",   # 測試 context 記憶
    ]

    for q in questions:
        print(f"[問] {q}")
        response = chat.send_message(
            f"請用台灣用語的繁體中文回答，不要使用 markdown 格式。\n\n問題：{q}"
        )
        answer = response.text or "（無回應）"
        print(f"[答] {answer[:500]}")
        print()


# ── 主程式 ────────────────────────────────────────────────

async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if not GCP_PROJECT:
        print("❌ 請先設定 GOOGLE_CLOUD_PROJECT 環境變數\n")
        print("  export GOOGLE_CLOUD_PROJECT=your-project-id")
        sys.exit(1)

    if mode in ("maps", "all"):
        await demo_maps()

    if mode in ("chat", "all"):
        demo_chat()


if __name__ == "__main__":
    asyncio.run(main())
