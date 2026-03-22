# linebot-spot-finder

LINE Bot 聚會地點小幫手。核心特色是 **Tool Combo**：在單次 Gemini API 呼叫中同時啟用 Google Search（內建）與自訂函式，實現真正的 Agentic 搜尋體驗。

---

## Tool Combo — 核心功能

Tool Combo 讓模型在一次呼叫裡同時使用多種工具：

- **Google Search**（built-in）— 即時網路搜尋
- **`check_reservation_availability`**（custom function）— 查詢餐廳訂位狀況

模型可以自行決定要呼叫哪些工具、依序組合結果，最終回覆使用者。

### Agentic Loop 流程

```
用戶傳送文字問題
       │
       ▼
┌─────────────────────────────────────┐
│  Step 1: 第一次 Gemini API 呼叫      │
│  tools = [google_search,             │
│           check_reservation_fn]      │
│  include_server_side_tool_           │
│  invocations = True                  │
└────────────────┬────────────────────┘
                 │
                 ▼
       偵測 function_call parts？
          ╱               ╲
        是                  否
        │                   │
        ▼                   ▼
┌──────────────┐     直接回傳 response.text
│ Step 2: 執行  │
│ 自訂函式並    │
│ 組建 history  │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Step 3: 第二次 Gemini API 呼叫      │
│  contents = history (含函式結果)     │
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

用戶傳送文字（有位置）──► Tool Combo（Google Search + 訂位查詢）
用戶傳送文字（無位置）──► Gemini Chat + Google Search（fallback）
/clear ──► 清除 session（含 lat/lng）
```

---

## 技術棧

- `google-genai` — Gemini API（Vertex AI）：Tool Combo、Maps Grounding、Chat
- `line-bot-sdk` — LINE Messaging API
- `fastapi` + `uvicorn` — Webhook server
- Model (Tool Combo): `gemini-3-flash-preview`
- Model (fallback chat / Maps Grounding): 由 `CHAT_MODEL` 環境變數控制

---

## 自訂工具說明

| 工具 | 類型 | 說明 |
|------|------|------|
| `google_search` | built-in | Gemini 即時網路搜尋 |
| `check_reservation_availability(restaurant_name, party_size)` | custom function | 查詢餐廳訂位狀況（mock 實作，以餐廳名稱 hash 決定結果，具確定性） |
| Google Maps Grounding | built-in | 依 GPS 座標搜尋附近地點（Postback 路徑） |

---

## 環境需求

- Python 3.10+
- Google Cloud 專案，已啟用 Vertex AI API
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
| `GOOGLE_CLOUD_LOCATION` | — | Vertex AI 區域（預設 `us-central1`）|
| `CHAT_MODEL` | — | Fallback chat 模型（預設 `gemini-2.5-flash`）|
| `SESSION_TIMEOUT_MINUTES` | — | Session 過期時間（預設 `30`）|
| `MAX_HISTORY_LENGTH` | — | 最大對話歷史筆數（預設 `20`）|

Tool Combo 路徑固定使用 `gemini-3-flash-preview`，不受 `CHAT_MODEL` 影響。

---

## 測試

### 安裝測試依賴

```bash
pip install pytest pytest-asyncio
```

### 執行測試

```bash
pytest tests/ -v
```

### 測試案例說明

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
```

### 測試架構說明

所有測試使用 `unittest.mock` 隔離外部依賴：
- `line_bot_api` → `AsyncMock`，避免真實發送 LINE 訊息
- `search_nearby_places` → `AsyncMock`，避免呼叫 Vertex AI Maps Grounding
- `tool_combo_search` → `AsyncMock`，避免呼叫 Gemini Tool Combo API
- `SessionManager` → 使用真實實作（純記憶體，無 IO）

---

## 專案結構

```
linebot-spot-finder/
├── main.py                    # Webhook handler（FastAPI）
├── demo.py                    # 本機快速測試腳本
├── requirements.txt
├── .env.example
├── config/
│   └── settings.py            # 環境變數讀取
├── loader/
│   ├── maps_grounding.py      # Maps Grounding API 呼叫（Postback 路徑）
│   └── tool_combo.py          # Tool Combo：google_search + 自訂函式（主路徑）
├── services/
│   ├── line_service.py        # LINE 訊息工具、錯誤格式化
│   └── session_manager.py     # 對話 Session TTL 管理（含 metadata 儲存）
└── tests/
    └── test_main.py           # 單元測試
```
