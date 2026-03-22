# linebot-spot-finder

LINE Bot 聚會地點小幫手。傳位置 → 選類型 → 取得附近餐廳 / 加油站 / 停車場推薦。文字訊息則走 Gemini + Google Search Grounding 對話。

## 核心功能

| 用戶動作 | Bot 回應 |
|---------|---------|
| 傳送 GPS 位置 | Quick Reply 選擇搜尋類型 |
| 點選「找餐廳」| Maps Grounding 回傳附近評價資訊 |
| 輸入文字問題 | Gemini Chat + Google Search 搜尋回答 |
| `/clear` | 清除對話記憶 |

## 技術棧

- `google-genai` — Gemini API（Vertex AI），Maps Grounding、Chat、Search Grounding
- `line-bot-sdk` — LINE Messaging API
- `fastapi` + `uvicorn` — Webhook server

## 環境需求

- Python 3.10+
- Google Cloud 專案，已啟用 Vertex AI API
- Application Default Credentials（`gcloud auth application-default login`）

## 安裝與啟動

```bash
# 安裝依賴
pip install -r requirements.txt

# 複製環境變數範本
cp .env.example .env
# 編輯 .env，填入 ChannelSecret、ChannelAccessToken、GOOGLE_CLOUD_PROJECT

# 本地啟動（使用 ngrok 或 localtunnel 對外公開）
uvicorn main:app --reload --port 8000
```

---

## Demo Script

不需要 LINE Bot，直接在終端機測試兩個核心功能。

```bash
# 設定 GCP 專案
export GOOGLE_CLOUD_PROJECT=your-project-id

# 全部測試
python demo.py

# 只測 Maps Grounding
python demo.py maps

# 只測 Gemini Chat（含 Google Search）
python demo.py chat
```

### 預期輸出範例

**Maps Grounding（`python demo.py maps`）**

```
──────────────────────────────────────────────────
Maps Grounding Demo
──────────────────────────────────────────────────
座標：25.0441, 121.5598（市民大道附近）

[查詢] 預設查詢（restaurant）
🍴 附近的餐廳：

1. 老王熱炒  ★★★★☆  距離約 200m
   地址：台北市信義區市民大道五段 XX 號

2. 豐盛食堂  ★★★★★  距離約 350m
   地址：台北市信義區松高路 XX 號
...
```

**Gemini Chat（`python demo.py chat`）**

```
──────────────────────────────────────────────────
Gemini Chat Demo（含 Google Search Grounding）
──────────────────────────────────────────────────

[問] 信義區市民大道附近有哪些值得推薦的熱炒餐廳？
[答] 信義區市民大道附近有幾間評價不錯的熱炒餐廳：
1. 老王熱炒 — Google 評分 4.5 顆星，主打現炒台式料理...

[問] 剛才提到的這些店，哪一間評價最高？
[答] 根據剛才的資訊，老王熱炒的評分最高，達到 4.5 顆星...
```

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
  test_create_session            — 首次呼叫建立新 session
  test_reuse_existing_session    — 同一 user 不重複建立
  test_clear_session             — /clear 後 session 消失
  test_add_and_get_history       — 對話歷史正確累積
  test_history_trim              — 超過 max_history_length 自動裁切

TestHandleText
  test_clear_command             — 傳 /clear 回覆重置確認訊息
  test_chat_reply                — 文字訊息觸發 Gemini 並回覆

TestHandleLocation
  test_location_returns_quick_reply     — 傳位置後出現三個 Quick Reply 按鈕
  test_location_address_in_reply        — 地址顯示在回覆文字中
  test_postback_data_contains_coordinates — 按鈕的 postback data 包含正確座標

TestHandlePostback
  test_search_nearby_restaurant  — 點選餐廳觸發 Maps Grounding 搜尋
  test_invalid_postback_json     — 非法 JSON 不崩潰
  test_unknown_action_ignored    — 未知 action 不觸發搜尋
```

### 測試架構說明

所有測試使用 `unittest.mock` 隔離外部依賴：
- `line_bot_api` → `AsyncMock`，避免真實發送 LINE 訊息
- `search_nearby_places` → `AsyncMock`，避免呼叫 Vertex AI
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
│   └── maps_grounding.py      # Maps Grounding API 呼叫
├── services/
│   ├── line_service.py        # LINE 訊息工具、錯誤格式化
│   └── session_manager.py     # 對話 Session TTL 管理
└── tests/
    └── test_main.py           # 單元測試
```

## 環境變數

| 變數 | 必填 | 說明 |
|------|------|------|
| `ChannelSecret` | ✅ | LINE Channel Secret |
| `ChannelAccessToken` | ✅ | LINE Channel Access Token |
| `GOOGLE_CLOUD_PROJECT` | ✅ | GCP 專案 ID |
| `GOOGLE_CLOUD_LOCATION` | — | Vertex AI 區域（預設 `us-central1`）|
| `CHAT_MODEL` | — | Gemini 模型（預設 `gemini-2.5-flash`）|
| `SESSION_TIMEOUT_MINUTES` | — | Session 過期時間（預設 `30`）|
| `MAX_HISTORY_LENGTH` | — | 最大對話歷史筆數（預設 `20`）|
