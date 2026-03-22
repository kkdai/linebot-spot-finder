"""
Tool Combo: Google Search (built-in) + custom function in a single Gemini API call.

Uses the agentic loop pattern:
  1. First call with built-in google_search + custom function declarations.
  2. Detect function_call parts in the response.
  3. Execute custom functions and feed results back.
  4. Second call to produce the final answer.

Model: gemini-3-flash-preview
"""

import hashlib
import logging
import os
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Custom function declaration
# ──────────────────────────────────────────────────────────────────────────────

CHECK_RESERVATION_FN = types.FunctionDeclaration(
    name="check_reservation_availability",
    description=(
        "Check whether a restaurant currently accepts reservations and "
        "has availability for the requested party size."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "restaurant_name": types.Schema(
                type=types.Type.STRING,
                description="The name of the restaurant to check.",
            ),
            "party_size": types.Schema(
                type=types.Type.INTEGER,
                description="Number of people in the party (default 4).",
            ),
        },
        required=["restaurant_name"],
    ),
)

TOOL_COMBO_MODEL = "gemini-3-flash-preview"


# ──────────────────────────────────────────────────────────────────────────────
# Mock implementation (deterministic, hash-based)
# ──────────────────────────────────────────────────────────────────────────────

def _mock_check_reservation(restaurant_name: str, party_size: int = 4) -> dict:
    """
    Deterministic mock for reservation availability.

    Uses the SHA-256 hash of the restaurant name to decide availability so that
    tests can predict the result without any randomness.

    Returns a dict that is JSON-serialisable and safe to pass back to Gemini.
    """
    digest = hashlib.sha256(restaurant_name.encode("utf-8")).digest()
    # Use the first byte to determine availability deterministically.
    available = digest[0] % 2 == 0

    if available:
        # Use the second byte to derive a mock wait time (0-30 minutes).
        wait_minutes = digest[1] % 31
        return {
            "restaurant_name": restaurant_name,
            "party_size": party_size,
            "available": True,
            "wait_minutes": wait_minutes,
            "message": (
                f"{restaurant_name} 目前可接受 {party_size} 人訂位，"
                f"等待時間約 {wait_minutes} 分鐘。"
            ),
        }
    else:
        return {
            "restaurant_name": restaurant_name,
            "party_size": party_size,
            "available": False,
            "wait_minutes": None,
            "message": f"{restaurant_name} 目前訂位已滿，無法接受 {party_size} 人訂位。",
        }


# ──────────────────────────────────────────────────────────────────────────────
# Function dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _execute_function(name: str, args: dict) -> Any:
    """Route a function_call from Gemini to the correct local implementation."""
    if name == "check_reservation_availability":
        restaurant_name = args.get("restaurant_name", "")
        party_size = int(args.get("party_size", 4))
        return _mock_check_reservation(restaurant_name, party_size)
    logger.warning("Unknown function called by model: %s", name)
    return {"error": f"Unknown function: {name}"}


# ──────────────────────────────────────────────────────────────────────────────
# Main async entry point
# ──────────────────────────────────────────────────────────────────────────────

async def tool_combo_search(query: str, lat: float, lng: float) -> str:
    """
    Perform a Tool Combo search: Google Search + check_reservation_availability
    in a single model invocation, followed by an agentic function-call loop.

    Args:
        query: The user's free-text question.
        lat:   Latitude of the user's current location.
        lng:   Longitude of the user's current location.

    Returns:
        The model's final text answer.
    """
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    if not project:
        logger.error("GOOGLE_CLOUD_PROJECT is not set; cannot use Tool Combo.")
        return "❌ 抱歉，Google Cloud 專案未設定，無法使用 Tool Combo 搜尋。"

    client = genai.Client(
        vertexai=True,
        project=project,
        location=location,
        http_options=types.HttpOptions(api_version="v1"),
    )

    # Build a location-enriched prompt.
    enriched_query = (
        f"用戶目前位置：緯度 {lat}，經度 {lng}。\n"
        f"請用台灣用語的繁體中文回答，不要使用 markdown 格式。\n\n"
        f"問題：{query}"
    )

    tool_config = types.GenerateContentConfig(
        tools=[
            types.Tool(
                google_search=types.ToolGoogleSearch(),
                function_declarations=[CHECK_RESERVATION_FN],
            )
        ],
        include_server_side_tool_invocations=True,
    )

    # ── Step 1: First call ────────────────────────────────────────────────────
    logger.info("Tool Combo Step 1: sending query to %s", TOOL_COMBO_MODEL)
    try:
        response = client.models.generate_content(
            model=TOOL_COMBO_MODEL,
            contents=enriched_query,
            config=tool_config,
        )
    except Exception as e:
        logger.error("Tool Combo Step 1 failed: %s", e, exc_info=True)
        return f"❌ 抱歉，搜尋時發生錯誤：{str(e)[:120]}"

    # ── Step 2: Build history and handle function calls ───────────────────────
    history = [
        types.Content(role="user", parts=[types.Part(text=enriched_query)]),
        response.candidates[0].content,
    ]

    function_call_found = False
    for part in response.candidates[0].content.parts:
        if part.function_call:
            function_call_found = True
            fn = part.function_call
            fn_name = fn.name
            fn_args = dict(fn.args) if fn.args else {}

            logger.info("Tool Combo: executing function '%s' with args %s", fn_name, fn_args)
            result = _execute_function(fn_name, fn_args)

            history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            id=fn.id,
                            name=fn_name,
                            response=result,
                        )
                    ],
                )
            )

    # ── Step 3: Final call (only needed when function calls were made) ─────────
    if function_call_found:
        logger.info("Tool Combo Step 3: sending function results back to model")
        try:
            final = client.models.generate_content(
                model=TOOL_COMBO_MODEL,
                contents=history,
                config=tool_config,
            )
            return final.text or "（無法取得回覆）"
        except Exception as e:
            logger.error("Tool Combo Step 3 failed: %s", e, exc_info=True)
            return f"❌ 抱歉，整合搜尋結果時發生錯誤：{str(e)[:120]}"

    # No function calls — return the first response directly.
    return response.text or "（無法取得回覆）"
