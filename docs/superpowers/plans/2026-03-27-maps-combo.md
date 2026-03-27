# Maps Combo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `tool_combo.py`'s Google Search + mock function with Google Maps grounding + Places API function tool, so a single Gemini call delivers real restaurant ratings, addresses, and review summaries.

**Architecture:** `tool_combo_search()` sends one request to Gemini with two tools attached: `google_maps` (built-in grounding) and `search_nearby_restaurants` (custom function). When Gemini emits a `function_call`, Python calls Places API (New) and feeds results back; Gemini then produces a natural-language reply.

**Tech Stack:** `google-genai` (Vertex AI), `httpx` (Places API HTTP), `pytest` + `unittest.mock`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config/settings.py` | Modify | Add `GOOGLE_MAPS_API_KEY` |
| `config/__init__.py` | Modify | Export `GOOGLE_MAPS_API_KEY` |
| `loader/tool_combo.py` | Modify | Replace mock with Places API; swap google_search → google_maps |
| `tests/test_tool_combo.py` | Create | Unit tests for Places API integration |
| `tests/test_main.py` | Modify | Update TestToolCombo mocks (function name changed) |

---

### Task 1: Add GOOGLE_MAPS_API_KEY to config

**Files:**
- Modify: `config/settings.py`
- Modify: `config/__init__.py`
- Test: `tests/test_tool_combo.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_combo.py`:

```python
"""Unit tests for loader/tool_combo.py"""
import os
import pytest


def test_google_maps_api_key_required(monkeypatch):
    """GOOGLE_MAPS_API_KEY must be set or config raises."""
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    # Force reload so the env change takes effect
    import importlib
    import config.settings as s
    monkeypatch.setenv("ChannelSecret", "x")
    monkeypatch.setenv("ChannelAccessToken", "x")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "x")
    with pytest.raises(EnvironmentError, match="GOOGLE_MAPS_API_KEY"):
        importlib.reload(s)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/al03034132/Documents/linebot-spot-finder
pytest tests/test_tool_combo.py::test_google_maps_api_key_required -v
```

Expected: FAIL — `EnvironmentError` not raised because key doesn't exist in settings yet.

- [ ] **Step 3: Add key to settings.py**

In `config/settings.py`, after the existing `CHAT_MODEL` line add:

```python
# Google Maps Platform
GOOGLE_MAPS_API_KEY = get_required("GOOGLE_MAPS_API_KEY")
```

- [ ] **Step 4: Export from config/__init__.py**

Replace the contents of `config/__init__.py` with:

```python
from .settings import (
    CHANNEL_SECRET,
    CHANNEL_ACCESS_TOKEN,
    GCP_PROJECT,
    GCP_LOCATION,
    CHAT_MODEL,
    SESSION_TIMEOUT_MINUTES,
    MAX_HISTORY_LENGTH,
    GOOGLE_MAPS_API_KEY,
)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_tool_combo.py::test_google_maps_api_key_required -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config/settings.py config/__init__.py tests/test_tool_combo.py
git commit -m "feat: add GOOGLE_MAPS_API_KEY to config"
```

---

### Task 2: Implement `_call_places_api`

**Files:**
- Modify: `loader/tool_combo.py`
- Test: `tests/test_tool_combo.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_combo.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_tool_combo.py::test_call_places_api_returns_restaurants -v
```

Expected: FAIL — `ImportError: cannot import name '_call_places_api'`

- [ ] **Step 3: Implement `_call_places_api` in tool_combo.py**

At the top of `loader/tool_combo.py`, replace the entire file with the following (preserving the module docstring):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_tool_combo.py::test_call_places_api_returns_restaurants -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add loader/tool_combo.py tests/test_tool_combo.py
git commit -m "feat: implement Places API combo (Maps grounding + search_nearby_restaurants)"
```

---

### Task 3: Handle Places API error cases

**Files:**
- Test: `tests/test_tool_combo.py`
- Modify: `loader/tool_combo.py` (already implemented — just add tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_tool_combo.py`:

```python
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
```

- [ ] **Step 2: Add missing import to test file**

At the top of `tests/test_tool_combo.py`, ensure `httpx` is imported:

```python
import httpx
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
pytest tests/test_tool_combo.py -v
```

Expected: All 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_tool_combo.py
git commit -m "test: add Places API error handling and dispatcher tests"
```

---

### Task 4: Update test_main.py for new function name

**Files:**
- Modify: `tests/test_main.py`

The old mock patched `check_reservation_availability` behaviour indirectly through `tool_combo_search`. Since `tool_combo_search` is still mocked at the call site in `test_main.py`, no function-name changes are needed there — but verify the existing tests still pass.

- [ ] **Step 1: Run existing test_main.py tests**

```bash
pytest tests/test_main.py -v
```

Expected: All tests PASS (tool_combo_search is fully mocked, so internal changes don't affect these tests).

- [ ] **Step 2: If any tests fail, fix the mock**

If `TestToolCombo::test_tool_combo_triggered_when_location_known` fails, check that the patch path is still `main.tool_combo_search` — it should be unchanged.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests PASS

- [ ] **Step 4: Commit if any fixes were needed**

```bash
git add tests/test_main.py
git commit -m "test: verify test_main compatibility after tool_combo rewrite"
```

---

### Task 5: Update Cloud Run environment variable

**Files:** None (Cloud Run config change)

- [ ] **Step 1: Verify GOOGLE_MAPS_API_KEY is set in Cloud Run**

```bash
gcloud run services describe linebot-spot-finder \
  --project=line-vertex \
  --region=europe-west1 \
  --format="value(spec.template.spec.containers[0].env)"
```

Confirm `GOOGLE_MAPS_API_KEY` appears in the output.

- [ ] **Step 2: If missing, set it**

```bash
gcloud run services update linebot-spot-finder \
  --project=line-vertex \
  --region=europe-west1 \
  --update-env-vars GOOGLE_MAPS_API_KEY=<your-key>
```

- [ ] **Step 3: Deploy latest commit**

```bash
git push
```

Cloud Build will trigger automatically if linked. Verify the new revision is serving traffic:

```bash
gcloud run revisions list \
  --service=linebot-spot-finder \
  --project=line-vertex \
  --region=europe-west1 \
  --limit=3
```

Expected: Latest revision shows `100%` traffic.

---

## Self-Review

**Spec coverage:**
- ✅ `google_maps` replaces `google_search` — Task 2 (tool_config change)
- ✅ `search_nearby_restaurants` replaces `check_reservation_availability` — Task 2
- ✅ Places API fields: rating, address, reviews — Task 2 (`_call_places_api`)
- ✅ `lat/lng` injected by Python, not Gemini — Task 2 (`_execute_function` signature)
- ✅ `GOOGLE_MAPS_API_KEY` added to config — Task 1
- ✅ Tests updated — Tasks 3 & 4
- ✅ Cloud Run env var — Task 5

**Placeholder scan:** No TBD, no "implement later", all code blocks complete.

**Type consistency:**
- `_call_places_api(lat, lng, keyword, min_rating, radius_m)` — defined Task 2, used in Task 3 tests with same signature ✅
- `_execute_function(name, args, lat, lng)` — defined Task 2, tested Task 3 ✅
- `SEARCH_NEARBY_RESTAURANTS_FN` — defined and used in same Task 2 file ✅
