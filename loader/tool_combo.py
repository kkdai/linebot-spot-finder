"""
Tool Combo: Google Maps grounding + Places API custom function in a single Gemini call.

Uses the agentic loop pattern:
  1. First call with google_maps grounding + search_nearby_restaurants function declaration.
  2. Detect function_call parts in the response.
  3. Call Places API and feed results back.
  4. Second call to produce the final answer.

Model: gemini-3-flash-preview
"""

import logging
import os
from typing import Any

import httpx
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

TOOL_COMBO_MODEL = "gemini-3-flash-preview"
PLACES_API_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACES_FIELD_MASK = (
    "places.displayName,"
    "places.rating,"
    "places.userRatingCount,"
    "places.formattedAddress,"
    "places.reviews"
)
MAX_RESULTS = 5
MAX_REVIEWS_PER_PLACE = 3


# ──────────────────────────────────────────────────────────────────────────────
# Function declaration
# ──────────────────────────────────────────────────────────────────────────────

SEARCH_NEARBY_RESTAURANTS_FN = types.FunctionDeclaration(
    name="search_nearby_restaurants",
    description=(
        "用 Google Places API 搜尋附近餐廳，回傳評分、地址與用戶評論。"
        "lat/lng 由系統自動帶入，不需要提供。"
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "keyword": types.Schema(
                type=types.Type.STRING,
                description="餐廳類型或關鍵字，例如：熱炒、火鍋、義式",
            ),
            "min_rating": types.Schema(
                type=types.Type.NUMBER,
                description="最低評分門檻（1–5），預設 4.0",
            ),
            "radius_m": types.Schema(
                type=types.Type.INTEGER,
                description="搜尋半徑（公尺），預設 1000",
            ),
        },
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# Places API implementation
# ──────────────────────────────────────────────────────────────────────────────

def _call_places_api(
    lat: float,
    lng: float,
    keyword: str = "",
    min_rating: float = 4.0,
    radius_m: int = 1000,
) -> dict:
    """
    Call Google Places API (New) searchNearby and return structured data.

    lat/lng come from session metadata (injected by dispatcher, not from Gemini).
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

    body: dict = {
        "includedTypes": ["restaurant"],
        "maxResultCount": MAX_RESULTS,
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radiusMeters": radius_m,
            }
        },
    }
    if keyword:
        body["textQuery"] = keyword

    try:
        response = httpx.post(
            PLACES_API_URL,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            json=body,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error("Places API error: %s", e, exc_info=True)
        return {"error": str(e), "restaurants": []}

    restaurants = []
    for place in data.get("places", []):
        rating = place.get("rating", 0)
        if rating < min_rating:
            continue
        reviews = [
            r["text"]["text"]
            for r in place.get("reviews", [])[:MAX_REVIEWS_PER_PLACE]
            if r.get("text", {}).get("text")
        ]
        restaurants.append({
            "name": place.get("displayName", {}).get("text", ""),
            "address": place.get("formattedAddress", ""),
            "rating": rating,
            "rating_count": place.get("userRatingCount", 0),
            "reviews": reviews,
        })

    logger.info("Places API returned %d restaurants (min_rating=%.1f)", len(restaurants), min_rating)
    return {"restaurants": restaurants}


# ──────────────────────────────────────────────────────────────────────────────
# Function dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def _execute_function(name: str, args: dict, lat: float, lng: float) -> Any:
    """Route a function_call from Gemini to the correct local implementation."""
    if name == "search_nearby_restaurants":
        return _call_places_api(
            lat=lat,
            lng=lng,
            keyword=args.get("keyword", ""),
            min_rating=float(args.get("min_rating", 4.0)),
            radius_m=int(args.get("radius_m", 1000)),
        )
    logger.warning("Unknown function called by model: %s", name)
    return {"error": f"Unknown function: {name}"}


# ──────────────────────────────────────────────────────────────────────────────
# Main async entry point
# ──────────────────────────────────────────────────────────────────────────────

async def tool_combo_search(query: str, lat: float, lng: float) -> str:
    """
    Perform a Tool Combo search: Google Maps grounding + search_nearby_restaurants
    in a single model invocation, followed by an agentic function-call loop.

    Args:
        query: The user's free-text question.
        lat:   Latitude from session metadata.
        lng:   Longitude from session metadata.

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

    enriched_query = (
        f"用戶目前位置：緯度 {lat}，經度 {lng}。\n"
        f"請用台灣用語的繁體中文回答，不要使用 markdown 格式。\n\n"
        f"問題：{query}"
    )

    tool_config = types.GenerateContentConfig(
        tools=[
            types.Tool(
                google_maps=types.GoogleMaps(),
                function_declarations=[SEARCH_NEARBY_RESTAURANTS_FN],
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

    # ── Step 2: Handle function calls ─────────────────────────────────────────
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

            logger.info("Tool Combo: executing '%s' with args %s", fn_name, fn_args)
            result = _execute_function(fn_name, fn_args, lat, lng)

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

    # ── Step 3: Final call ────────────────────────────────────────────────────
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

    return response.text or "（無法取得回覆）"
