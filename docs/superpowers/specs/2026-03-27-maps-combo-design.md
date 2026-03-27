# Maps Combo Design

**Date:** 2026-03-27
**Goal:** Replace tool_combo.py's Google Search + mock function with Google Maps grounding + Places API function tool, implementing the Maps Grounding + Function Calling combo described in the Gemini API tooling updates blog (2026-03-17).

---

## Architecture

```
User sends location pin → session stores lat/lng
User sends text message → tool_combo_search(query, lat, lng)  [main.py — unchanged]
                           │
                           ▼
                   Gemini (gemini-2.5-flash)
                   tools: [google_maps + search_nearby_restaurants]
                           │
                     ┌─────┴──────┐
                     │             │
                Maps Grounding  function_call → Places API (New)
                (location context) (rating/address/reviews)
                     │             │
                     └─────┬───────┘
                           ▼
                   Gemini integrates both → natural language reply
```

---

## Changed Files

| File | Change |
|---|---|
| `loader/tool_combo.py` | Replace function declaration + implement Places API call |
| `config/settings.py` | Add `GOOGLE_MAPS_API_KEY` env var |
| `main.py` | No change |
| `tests/test_main.py` | Update TestToolCombo mocks |

---

## tool_combo.py Changes

### Function Declaration

```python
SEARCH_NEARBY_RESTAURANTS_FN = types.FunctionDeclaration(
    name="search_nearby_restaurants",
    description="用 Google Places API 搜尋附近餐廳，回傳評分、地址與評論摘要",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "keyword":    Schema(STRING, "餐廳類型或關鍵字，例如：熱炒、火鍋"),
            "min_rating": Schema(NUMBER, "最低評分門檻，預設 4.0"),
            "radius_m":   Schema(INTEGER, "搜尋半徑（公尺），預設 1000"),
        }
    )
)
```

`lat/lng` are NOT in the function declaration — they are injected by the Python dispatcher from session metadata to prevent Gemini from guessing coordinates.

### Tool Config

```python
# Before
types.Tool(
    google_search=types.GoogleSearch(),
    function_declarations=[CHECK_RESERVATION_FN],
)

# After
types.Tool(
    google_maps=types.GoogleMaps(),
    function_declarations=[SEARCH_NEARBY_RESTAURANTS_FN],
)
```

### Places API Call

- Endpoint: `POST https://places.googleapis.com/v1/places:searchNearby`
- Field mask: `places.displayName,places.rating,places.userRatingCount,places.formattedAddress,places.reviews`
- Max results: 5 restaurants
- Reviews: up to 3 per restaurant passed to Gemini for summarization

### Return Structure to Gemini

```python
{
    "restaurants": [
        {
            "name": "老王熱炒",
            "address": "台北市信義區...",
            "rating": 4.5,
            "rating_count": 328,
            "reviews": [
                "份量大、CP值高，朋友聚餐首選",
                "服務很快，菜色新鮮"
            ]
        },
        # up to 5 restaurants
    ]
}
```

---

## config/settings.py Changes

```python
GOOGLE_MAPS_API_KEY = get_required("GOOGLE_MAPS_API_KEY")
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `GOOGLE_MAPS_API_KEY` | Places API key (already set by user) |
| `GOOGLE_CLOUD_PROJECT` | Existing — unchanged |
| `GOOGLE_CLOUD_LOCATION` | Existing — now `us-central1` |

---

## What is Removed

- `CHECK_RESERVATION_FN` function declaration
- `_mock_check_reservation()` mock implementation
- `google_search` grounding in tool_combo

---

## Test Updates

`TestToolCombo` in `tests/test_main.py`:
- Mock `tool_combo_search` return value stays the same (already mocked at the call site)
- Add unit tests for `_search_nearby_restaurants()` with a mocked `httpx` response
- Verify function dispatcher routes `search_nearby_restaurants` correctly
