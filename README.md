# linebot-spot-finder

LINE Bot 聚會地點小幫手。核心特色是 **Tool Combo**：在單次 Gemini API 呼叫中同時啟用 Google Maps grounding 與 Places API 自訂函式，回傳真實餐廳評分、地址與評論摘要。

---

## Tool Combo — 核心功能

Tool Combo 讓模型在一次呼叫裡同時使用多種工具：

- **Google Maps grounding**（built-in）— 地圖情境感知
- **`search_nearby_restaurants`**（custom function）— 呼叫 Google Places API (New)，回傳評分、地址、評論

模型自行決定何時呼叫自訂函式、整合地圖情境，最終以自然語言回覆。

### Agentic Loop 流程

```
用戶傳送文字問題
       │
       ▼
┌─────────────────────────────────────┐
│  Step 1: 第一次 Gemini API 呼叫      │
│  tools = [google_maps,               │
│           search_nearby_restaurants] │
└────────────────┬────────────────────┘
                 │
                 ▼
       偵測 function_call parts？
          ╱               ╲
        是                  否
        │                   │
        ▼                   ▼
┌──────────────────┐   直接回傳 response.text
│ Step 2: 呼叫      │
│ Places API 並     │
│ 組建 history      │
└──────┬───────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Step 3: 第二次 Gemini API 呼叫      │
│  contents = history（含 Places 結果）│
└────────────────┬────────────────────┘
                 │
                 ▼
           回傳 final.text
```

### 完整訊息流程

```
用戶傳送 GPS 位置 ──► 儲存 lat/lng 到 session.metadata
                  └──► Quick Reply 選擇搜尋類型

用戶點選按鈕 ──► Postback ──► Maps Grounding（餐廳/加油站/停車場）

用戶傳送文字（有位置）──► Tool Combo（Maps grounding + Places API）
用戶傳送文字（無位置）──► Gemini Chat + Google Search（fallback）
/clear ──► 清除 session（含 lat/lng）
```

---

## 技術棧

- `google-genai` — Gemini API（Vertex AI）：Tool Combo、Maps Grounding、Chat
- `line-bot-sdk` — LINE Messaging API
- `fastapi` + `uvicorn` — Webhook server
- `httpx` — Places API HTTP 呼叫
- Model (Tool Combo): 由 `TOOL_COMBO_MODEL` 控制（預設 `gemini-2.5-flash`）
- Model (fallback chat / Maps Grounding): 由 `CHAT_MODEL` 控制（預設 `gemini-2.5-flash`）

---

## 自訂工具說明

| 工具 | 類型 | 說明 |
|------|------|------|
| `google_maps` | built-in | Gemini Maps grounding，依 GPS 座標提供地圖情境 |
| `search_nearby_restaurants(keyword, min_rating, radius_m)` | custom function | 呼叫 Google Places API (New) `searchNearby`，回傳最多 5 間餐廳的評分、地址、評論 |
| Google Maps Grounding（Postback） | built-in | 點選快速回覆按鈕時搜尋附近餐廳/加油站/停車場 |

---

## Demo Script

不需要 LINE Bot，直接在本機測試三個核心功能：

```bash
python demo.py maps        # Maps Grounding：依座標搜尋附近地點
python demo.py combo       # Tool Combo：主功能，Places API + Maps grounding
python demo.py chat        # Gemini Chat：fallback 對話路徑
python demo.py all         # 全部測試（預設）
```

### Demo 1 — Maps Grounding

```
座標：25.0441, 121.5598（信義區市民大道附近）

[查詢] 預設查詢（restaurant）
[查詢] 預設查詢（parking）
[查詢] 請找評價 4 顆星以上、適合多人聚餐的熱炒店，列出名稱和地址。
```

### Demo 2 — Tool Combo（主功能）

```
座標：25.0441, 121.5598（信義區市民大道附近）

[問] 請找評價 4 顆星以上、適合多人聚餐的熱炒店，列出名稱、地址和評論摘要。
[答] ...（Gemini 整合 Maps grounding + Places API 評分/評論後回覆）

[問] 附近有沒有 CP 值高的日式料理？
[答] ...
```

### Demo 3 — Gemini Chat（fallback）

```
[問] 信義區市民大道附近有哪些值得推薦的熱炒餐廳？
[答] ...

[問] 剛才提到的這些店，哪一間評價最高？
[答] ...（測試 context 記憶）
```

---

## 環境需求

- Python 3.10+
- Google Cloud 專案，已啟用 Vertex AI API 與 Places API (New)
- Application Default Credentials（`gcloud auth application-default login`）

---

## 安裝與啟動

```bash
# 安裝依賴
pip install -r requirements.txt

# 複製環境變數範本
cp .env.example .env
# 編輯 .env，填入必要環境變數

# 本地啟動（使用 ngrok 或 localtunnel 對外公開）
uvicorn main:app --reload --port 8000
```

---

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `ChannelSecret` | ✅ | LINE Channel Secret |
| `ChannelAccessToken` | ✅ | LINE Channel Access Token |
| `GOOGLE_CLOUD_PROJECT` | ✅ | GCP 專案 ID |
| `GOOGLE_MAPS_API_KEY` | ✅ | Google Maps Platform API Key（Places API 需要）|
| `GOOGLE_CLOUD_LOCATION` | — | Vertex AI 區域（預設 `us-central1`）|
| `CHAT_MODEL` | — | Fallback chat 模型（預設 `gemini-2.5-flash`）|
| `TOOL_COMBO_MODEL` | — | Tool Combo 模型（預設 `gemini-2.5-flash`）|
| `SESSION_TIMEOUT_MINUTES` | — | Session 過期時間（預設 `30`）|
| `MAX_HISTORY_LENGTH` | — | 最大對話歷史筆數（預設 `20`）|

---

## 測試

```bash
pytest tests/ -v
```

### 測試案例（23 個）

```
tests/test_main.py

TestSessionManager
  test_create_session                   — 首次呼叫建立新 session
  test_reuse_existing_session           — 同一 user 不重複建立
  test_clear_session                    — /clear 後 session 消失
  test_add_and_get_history              — 對話歷史正確累積
  test_history_trim                     — 超過 max_history_length 自動裁切

TestHandleText
  test_clear_command                    — 傳 /clear 回覆重置確認訊息
  test_chat_reply                       — 文字訊息（無位置）觸發 Gemini 並回覆

TestHandleLocation
  test_location_returns_quick_reply     — 傳位置後出現三個 Quick Reply 按鈕
  test_location_address_in_reply        — 地址顯示在回覆文字中
  test_postback_data_contains_coordinates — 按鈕的 postback data 包含正確座標

TestHandlePostback
  test_search_nearby_restaurant         — 點選餐廳觸發 Maps Grounding 搜尋
  test_invalid_postback_json            — 非法 JSON 不崩潰
  test_unknown_action_ignored           — 未知 action 不觸發搜尋

TestToolCombo
  test_tool_combo_triggered_when_location_known — 有位置時走 Tool Combo 路徑
  test_fallback_to_chat_without_location        — 無位置時走 fallback chat 路徑
  test_location_stored_in_session_metadata      — 傳位置後 lat/lng 存入 session.metadata

tests/test_tool_combo.py

  test_google_maps_api_key_required             — 缺少 GOOGLE_MAPS_API_KEY 時啟動報錯
  test_call_places_api_returns_restaurants      — 正確解析 Places API 回應
  test_call_places_api_filters_low_rating       — 過濾低於 min_rating 的餐廳
  test_call_places_api_handles_http_error       — HTTP 錯誤回傳空列表
  test_execute_function_routes_correctly        — dispatcher 正確路由至 _call_places_api
  test_execute_function_unknown_returns_error   — 未知函式回傳 error dict
  test_tool_combo_search_agentic_loop           — agentic loop 完整兩次呼叫驗證
```

### 測試架構說明

所有測試使用 `unittest.mock` 隔離外部依賴：
- `line_bot_api` → `AsyncMock`，避免真實發送 LINE 訊息
- `search_nearby_places` → `AsyncMock`，避免呼叫 Vertex AI Maps Grounding
- `tool_combo_search` → `AsyncMock`，避免呼叫 Gemini Tool Combo API
- `genai.Client` → `MagicMock`，tool_combo 單元測試中隔離 Vertex AI
- `SessionManager` → 使用真實實作（純記憶體，無 IO）

---

## 專案結構

```
linebot-spot-finder/
├── main.py                    # Webhook handler（FastAPI）
├── demo.py                    # 本機快速測試腳本
├── Dockerfile                 # Cloud Run 部署
├── requirements.txt
├── pytest.ini
├── .env.example
├── config/
│   ├── settings.py            # 環境變數讀取
│   └── __init__.py
├── loader/
│   ├── maps_grounding.py      # Maps Grounding API 呼叫（Postback 路徑）
│   └── tool_combo.py          # Tool Combo：google_maps + Places API（主路徑）
├── services/
│   ├── line_service.py        # LINE 訊息工具、錯誤格式化
│   └── session_manager.py     # 對話 Session TTL 管理（含 metadata 儲存）
└── tests/
    ├── conftest.py             # pytest 環境變數設定
    ├── test_main.py            # Webhook handler 測試
    └── test_tool_combo.py      # Tool Combo 與 Places API 測試
```
