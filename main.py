import json
import logging
import sys

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from google import genai
from google.genai import types
from linebot import AsyncLineBotApi, WebhookParser
from linebot.aiohttp_async_http_client import AiohttpAsyncHttpClient
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    LocationMessage,
    MessageEvent,
    PostbackEvent,
    TextMessage,
    TextSendMessage,
    QuickReply,
    QuickReplyButton,
    PostbackAction,
)
from linebot.models.sources import SourceGroup, SourceRoom, SourceUser

from config import (
    CHANNEL_SECRET,
    CHANNEL_ACCESS_TOKEN,
    GCP_PROJECT,
    GCP_LOCATION,
    CHAT_MODEL,
    SESSION_TIMEOUT_MINUTES,
    MAX_HISTORY_LENGTH,
)
from loader.maps_grounding import search_nearby_places
from loader.tool_combo import tool_combo_search
from services.line_service import LineService
from services.session_manager import get_session_manager

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# LINE Bot
aio_session = aiohttp.ClientSession()
async_http_client = AiohttpAsyncHttpClient(aio_session)
line_bot_api = AsyncLineBotApi(CHANNEL_ACCESS_TOKEN, async_http_client)
parser = WebhookParser(CHANNEL_SECRET)

# Gemini client (Vertex AI) — used for the fallback chat path only
gemini_client = genai.Client(
    vertexai=True,
    project=GCP_PROJECT,
    location=GCP_LOCATION,
    http_options=types.HttpOptions(api_version="v1"),
)

CHAT_CONFIG = types.GenerateContentConfig(
    temperature=0.7,
    max_output_tokens=2048,
    tools=[types.Tool(google_search=types.GoogleSearch())],
)

# Session manager (handles TTL + background cleanup)
session_manager = get_session_manager(
    timeout_minutes=SESSION_TIMEOUT_MINUTES,
    max_history_length=MAX_HISTORY_LENGTH,
)

app = FastAPI()


def _chat_factory():
    return gemini_client.chats.create(model=CHAT_MODEL, config=CHAT_CONFIG)


@app.on_event("startup")
async def startup():
    await session_manager.start_cleanup_task()


@app.on_event("shutdown")
async def shutdown():
    await session_manager.stop_cleanup_task()
    await aio_session.close()


@app.get("/")
def health_check():
    return "OK"


@app.post("/")
async def handle_webhook(request: Request):
    signature = request.headers["X-Line-Signature"]
    body = (await request.body()).decode()

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            await handle_message(event)
        elif isinstance(event, PostbackEvent):
            await handle_postback(event)

    return "OK"


async def handle_message(event: MessageEvent):
    if isinstance(event.source, (SourceGroup, SourceRoom)):
        return

    user_id = event.source.user_id

    if isinstance(event.message, TextMessage):
        await handle_text(event, user_id)
    elif isinstance(event.message, LocationMessage):
        await handle_location(event)


async def handle_text(event: MessageEvent, user_id: str):
    msg = event.message.text.strip()

    if msg in ("/clear", "/清除"):
        session_manager.clear_session(user_id)
        reply = TextSendMessage(text="✅ 對話已重置")
    else:
        try:
            session = session_manager.get_or_create_session(user_id, _chat_factory)

            # Primary path: Tool Combo when location is known
            lat = session.metadata.get("lat")
            lng = session.metadata.get("lng")

            if lat is not None and lng is not None:
                logger.info(
                    "Tool Combo path for user %s at (%.4f, %.4f)", user_id, lat, lng
                )
                answer = await tool_combo_search(msg, lat, lng)
            else:
                # Fallback: regular Gemini chat (no location context)
                logger.info("Fallback chat path for user %s (no location)", user_id)
                response = session.chat.send_message(
                    f"請用台灣用語的繁體中文回答，不要使用 markdown 格式。\n\n問題：{msg}"
                )
                answer = response.text or "（無法取得回覆）"

            session_manager.add_to_history(user_id, "user", msg)
            session_manager.add_to_history(user_id, "assistant", answer)
            reply = TextSendMessage(text=answer[:4500])

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            reply = TextSendMessage(text=LineService.format_error_message(e, "處理訊息"))

    await line_bot_api.reply_message(event.reply_token, [reply])


async def handle_location(event: MessageEvent):
    user_id = event.source.user_id
    lat = event.message.latitude
    lng = event.message.longitude
    address = event.message.address or "已記錄位置"

    # Persist coordinates in session metadata for Tool Combo
    session_manager.get_or_create_session(user_id, _chat_factory)
    session_manager.update_metadata(user_id, "lat", lat)
    session_manager.update_metadata(user_id, "lng", lng)
    logger.info("Stored location for user %s: (%.4f, %.4f)", user_id, lat, lng)

    quick_reply = QuickReply(items=[
        QuickReplyButton(action=PostbackAction(
            label="🍴 找餐廳",
            data=json.dumps({"action": "search_nearby", "place_type": "restaurant", "lat": lat, "lng": lng}),
            display_text="🍴 找餐廳",
        )),
        QuickReplyButton(action=PostbackAction(
            label="⛽ 找加油站",
            data=json.dumps({"action": "search_nearby", "place_type": "gas_station", "lat": lat, "lng": lng}),
            display_text="⛽ 找加油站",
        )),
        QuickReplyButton(action=PostbackAction(
            label="🅿️ 找停車場",
            data=json.dumps({"action": "search_nearby", "place_type": "parking", "lat": lat, "lng": lng}),
            display_text="🅿️ 找停車場",
        )),
    ])

    reply = TextSendMessage(
        text=f"📍 {address}\n\n請選擇要搜尋的類型：",
        quick_reply=quick_reply,
    )
    await line_bot_api.reply_message(event.reply_token, [reply])


async def handle_postback(event: PostbackEvent):
    user_id = event.source.user_id if isinstance(event.source, SourceUser) else None

    try:
        data = json.loads(event.postback.data)
    except json.JSONDecodeError:
        return

    if data.get("action") == "search_nearby" and user_id:
        await line_bot_api.reply_message(event.reply_token, [
            TextSendMessage(text="🔍 搜尋中，請稍候...")
        ])
        result = await search_nearby_places(
            latitude=data["lat"],
            longitude=data["lng"],
            place_type=data["place_type"],
        )
        await line_bot_api.push_message(user_id, [TextSendMessage(text=result)])
