"""
Unit tests for linebot-spot-finder

Run: pytest tests/ -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from linebot.models import (
    LocationMessage,
    MessageEvent,
    PostbackEvent,
    TextMessage,
    TextSendMessage,
)
from linebot.models.sources import SourceUser


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

def make_text_event(user_id: str, text: str) -> MagicMock:
    event = MagicMock(spec=MessageEvent)
    event.reply_token = "test-reply-token"
    event.source = MagicMock(spec=SourceUser)
    event.source.user_id = user_id
    event.message = MagicMock(spec=TextMessage)
    event.message.text = text
    return event


def make_location_event(user_id: str, lat: float, lng: float, address: str = "台北市信義區") -> MagicMock:
    event = MagicMock(spec=MessageEvent)
    event.reply_token = "test-reply-token"
    event.source = MagicMock(spec=SourceUser)
    event.source.user_id = user_id
    event.message = MagicMock(spec=LocationMessage)
    event.message.latitude = lat
    event.message.longitude = lng
    event.message.address = address
    return event


def make_postback_event(user_id: str, data: dict) -> MagicMock:
    event = MagicMock(spec=PostbackEvent)
    event.reply_token = "test-reply-token"
    event.source = MagicMock(spec=SourceUser)
    event.source.user_id = user_id
    event.postback = MagicMock()
    event.postback.data = json.dumps(data)
    return event


# ──────────────────────────────────────────────
# SessionManager tests
# ──────────────────────────────────────────────

class TestSessionManager:
    def test_create_session(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        chat_mock = MagicMock()
        session = mgr.get_or_create_session("user1", lambda: chat_mock)
        assert session.user_id == "user1"
        assert session.chat is chat_mock

    def test_reuse_existing_session(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        factory_calls = 0

        def factory():
            nonlocal factory_calls
            factory_calls += 1
            return MagicMock()

        mgr.get_or_create_session("user1", factory)
        mgr.get_or_create_session("user1", factory)
        assert factory_calls == 1  # factory called only once

    def test_clear_session(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        mgr.get_or_create_session("user1", MagicMock)
        assert mgr.clear_session("user1") is True
        assert mgr.clear_session("user1") is False  # already cleared

    def test_add_and_get_history(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        mgr.get_or_create_session("user1", MagicMock)
        mgr.add_to_history("user1", "user", "你好")
        mgr.add_to_history("user1", "assistant", "你好！有什麼可以幫你？")
        history = mgr.get_history("user1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_history_trim(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30, max_history_length=5)
        mgr.get_or_create_session("user1", MagicMock)
        for i in range(10):
            mgr.add_to_history("user1", "user", f"msg {i}")
        history = mgr.get_history("user1")
        assert len(history) == 5  # trimmed to max


# ──────────────────────────────────────────────
# handle_text tests
# ──────────────────────────────────────────────

class TestHandleText:
    @pytest.mark.asyncio
    async def test_clear_command(self):
        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        mgr.get_or_create_session("user1", MagicMock)

        with patch("main.session_manager", mgr), \
             patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_text
            event = make_text_event("user1", "/clear")
            await handle_text(event, "user1")

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert "重置" in messages[0].text

    @pytest.mark.asyncio
    async def test_chat_reply(self):
        mock_response = MagicMock()
        mock_response.text = "台北市信義區有很多熱炒店！"

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_response)

        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        mgr.get_or_create_session("user1", lambda: mock_chat)

        with patch("main.session_manager", mgr), \
             patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_text
            event = make_text_event("user1", "附近有什麼好吃的？")
            await handle_text(event, "user1")

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert "熱炒店" in messages[0].text


# ──────────────────────────────────────────────
# handle_location tests
# ──────────────────────────────────────────────

class TestHandleLocation:
    @pytest.mark.asyncio
    async def test_location_returns_quick_reply(self):
        with patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_location
            event = make_location_event("user1", 25.0330, 121.5654, "台北101")
            await handle_location(event)

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert messages[0].quick_reply is not None
            labels = [btn.action.label for btn in messages[0].quick_reply.items]
            assert any("餐廳" in l for l in labels)
            assert any("加油站" in l for l in labels)
            assert any("停車場" in l for l in labels)

    @pytest.mark.asyncio
    async def test_location_address_in_reply(self):
        with patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_location
            event = make_location_event("user1", 25.0330, 121.5654, "信義區市民大道")
            await handle_location(event)

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert "信義區市民大道" in messages[0].text

    @pytest.mark.asyncio
    async def test_postback_data_contains_coordinates(self):
        with patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_location
            event = make_location_event("user1", 25.0330, 121.5654)
            await handle_location(event)

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            # Parse postback data from first quick reply button
            first_btn_data = json.loads(messages[0].quick_reply.items[0].action.data)
            assert first_btn_data["lat"] == pytest.approx(25.0330)
            assert first_btn_data["lng"] == pytest.approx(121.5654)


# ──────────────────────────────────────────────
# handle_postback tests
# ──────────────────────────────────────────────

class TestHandlePostback:
    @pytest.mark.asyncio
    async def test_search_nearby_restaurant(self):
        with patch("main.line_bot_api") as mock_api, \
             patch("main.search_nearby_places", new_callable=AsyncMock) as mock_search:
            mock_api.reply_message = AsyncMock()
            mock_api.push_message = AsyncMock()
            mock_search.return_value = "🍴 附近的餐廳：\n\n1. 老王熱炒 ★★★★☆"

            from main import handle_postback
            event = make_postback_event("user1", {
                "action": "search_nearby",
                "place_type": "restaurant",
                "lat": 25.0330,
                "lng": 121.5654,
            })
            await handle_postback(event)

            mock_search.assert_called_once_with(
                latitude=25.0330,
                longitude=121.5654,
                place_type="restaurant",
            )
            push_args = mock_api.push_message.call_args
            assert "熱炒" in push_args[0][1][0].text

    @pytest.mark.asyncio
    async def test_invalid_postback_json(self):
        with patch("main.line_bot_api") as mock_api:
            mock_api.reply_message = AsyncMock()
            from main import handle_postback
            event = MagicMock(spec=PostbackEvent)
            event.source = MagicMock(spec=SourceUser)
            event.source.user_id = "user1"
            event.postback.data = "not-valid-json"
            # Should not raise
            await handle_postback(event)
            mock_api.reply_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_action_ignored(self):
        with patch("main.line_bot_api") as mock_api, \
             patch("main.search_nearby_places", new_callable=AsyncMock) as mock_search:
            mock_api.reply_message = AsyncMock()
            from main import handle_postback
            event = make_postback_event("user1", {"action": "unknown_action"})
            await handle_postback(event)
            mock_search.assert_not_called()


# ──────────────────────────────────────────────
# TestToolCombo
# ──────────────────────────────────────────────

class TestToolCombo:
    @pytest.mark.asyncio
    async def test_tool_combo_triggered_when_location_known(self):
        """When session has lat/lng, tool_combo_search is called instead of chat.send_message."""
        from services.session_manager import SessionManager

        mock_chat = MagicMock()
        # send_message should NOT be called in the Tool Combo path
        mock_chat.send_message = MagicMock(return_value=MagicMock(text="fallback"))

        mgr = SessionManager(timeout_minutes=30)
        session = mgr.get_or_create_session("user_tc1", lambda: mock_chat)
        # Pre-populate location metadata
        session.metadata["lat"] = 25.0330
        session.metadata["lng"] = 121.5654

        with patch("main.session_manager", mgr), \
             patch("main.line_bot_api") as mock_api, \
             patch("main.tool_combo_search", new_callable=AsyncMock) as mock_combo:
            mock_api.reply_message = AsyncMock()
            mock_combo.return_value = "Tool Combo 回覆：附近有老王熱炒"

            from main import handle_text
            event = make_text_event("user_tc1", "附近有什麼好吃的？")
            await handle_text(event, "user_tc1")

            # tool_combo_search must have been called with correct args
            mock_combo.assert_awaited_once_with("附近有什麼好吃的？", 25.0330, 121.5654)
            # chat.send_message must NOT have been called
            mock_chat.send_message.assert_not_called()

            # Reply should contain the Tool Combo result
            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert "老王熱炒" in messages[0].text

    @pytest.mark.asyncio
    async def test_fallback_to_chat_without_location(self):
        """When session has no lat/lng, uses the regular Gemini chat path."""
        mock_response = MagicMock()
        mock_response.text = "台北有很多美食！"

        mock_chat = MagicMock()
        mock_chat.send_message = MagicMock(return_value=mock_response)

        from services.session_manager import SessionManager
        mgr = SessionManager(timeout_minutes=30)
        mgr.get_or_create_session("user_tc2", lambda: mock_chat)
        # No lat/lng in metadata

        with patch("main.session_manager", mgr), \
             patch("main.line_bot_api") as mock_api, \
             patch("main.tool_combo_search", new_callable=AsyncMock) as mock_combo:
            mock_api.reply_message = AsyncMock()

            from main import handle_text
            event = make_text_event("user_tc2", "台北有什麼好吃的？")
            await handle_text(event, "user_tc2")

            # tool_combo_search must NOT have been called
            mock_combo.assert_not_awaited()
            # Fallback chat.send_message must have been called
            mock_chat.send_message.assert_called_once()

            call_args = mock_api.reply_message.call_args
            messages = call_args[0][1]
            assert "美食" in messages[0].text

    @pytest.mark.asyncio
    async def test_location_stored_in_session_metadata(self):
        """Sending a location pin stores lat/lng in session.metadata."""
        from services.session_manager import SessionManager

        mgr = SessionManager(timeout_minutes=30)

        with patch("main.session_manager", mgr), \
             patch("main.line_bot_api") as mock_api, \
             patch("main._chat_factory", return_value=MagicMock()):
            mock_api.reply_message = AsyncMock()

            from main import handle_location
            event = make_location_event("user_tc3", 25.0441, 121.5598, "市民大道")
            await handle_location(event)

            session = mgr.get_session("user_tc3")
            assert session is not None
            assert session.metadata.get("lat") == pytest.approx(25.0441)
            assert session.metadata.get("lng") == pytest.approx(121.5598)
