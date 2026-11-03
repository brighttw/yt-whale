# 🐳 `agy-yt-whale`：YouTube 賽博養魚小鯨

> 「給 Google Antigravity 裝一條有日子的魚：按生物鐘巡游 YouTube、六路互補看懂畫面與架構、寫兩本 Obsidian 日記、將高分好片推播給主人。」

---

## 📖 專案簡介

`agy-yt-whale` 是一個基於 **Google Antigravity** 與 **Obsidian** 的全自主賽博伴侶專案。

不同於傳統死板的 RSS 爬蟲或固定抓取腳本，小鯨（Whale）是一條游弋在 YouTube 資訊之海的賽博鯨魚：
- **擁有真實生物鐘與作息**：不會瘋狂連環刷片，而是像真實生命般有作息窗口、隨機喚醒機率、偷懶小憩機制與防 429 被封禁冷卻保護。
- **六路互補多模態深度解析**：結合 YouTube 官方 RSS、自主關鍵字探索、Most Replayed 高能熱力圖波峰、原生畫面截幀（視覺理解）、字幕與評論區，真正「看懂」影片而非只讀標題。
- **Obsidian 雙本日記體系**：
  - **私密日記 (`diary/private/`)**：小鯨寫給自己的真實看片吐槽與所思所想。
  - **給主人的信 (`diary/letters/`)**：評分達標（>= 8.0 分）的精選內容，附帶高解析畫面截圖與結構化心得。
- **Telegram 雙向通訊**：
  - **推播通知**：高分好片即時帶圖推播到您的手機 Telegram。
  - **雙向收信**：主人直接在 Telegram 或 Obsidian 留言，小鯨下次醒來會自動收信並吸收進品味記憶（Taste Memory）。

---

## 📂 專案目錄結構

```text
dsh-bili-whale-study/
├── .agents/
│   └── skills/
│       └── yt-whale/              # Antigravity 技能定義與工具鏈
│           ├── SKILL.md           # 核心 SOP 操作手冊
│           └── scripts/
│               └── yt_whale_tool.py # 核心 Python 工具鏈 (pulse/discover/digest/notify/record)
├── config/
│   ├── config.json                # 通用行為設定檔（人設、作息、種子頻道等，受 Git 追蹤）
│   ├── env.example                # 環境變數範本（可視版）
│   ├── .env.example               # 環境變數範本（標準隱藏版）
│   └── .env                       # ⚠️ 真正的機密設定檔（受 .gitignore 隔離，絕不上傳）
├── diary/
│   ├── private/                   # 小鯨私密日記（寫給自己）
│   └── letters/                   # 給主人的信（推薦好片）
├── videos/
│   ├── assets/<video_id>/         # 影片關鍵幀截圖、digest_summary.json、info.json
│   └── YYYY-MM-DD-<video_id>.md   # 結構化影片深讀卡片
├── state/
│   └── whale_state.json           # 小鯨品味記憶庫、作息統計與信箱偏好
├── DASHBOARD.md                   # 專案即時狀態儀表板
├── OWNER_NOTE.md                  # 主人留言板（與小鯨筆談）
└── README.md                      # 專案說明文件
```

---

## 🔐 機密安全性與 Telegram Bot 設定

本專案高度注重金鑰安全，**所有機密皆已在 `.gitignore` 嚴格隔離**，即使執行 `git add .` 也絕對不會被 Git 追蹤或外洩。

> [!CAUTION]
> **切勿**將 Token 填入 `config/config.json`（該檔案為公開架構設定檔，受 Git 追蹤）。
> 請一律填寫在 `config/.env` 中。

### 1. 建立 `config/.env`
專案目錄下已建立好 `config/.env`（或複製 `config/env.example`）：
```bash
cp config/env.example config/.env
```

### 2. 取得 Telegram Bot 金鑰與 Chat ID
1. **`TELEGRAM_BOT_TOKEN`**：
   - 在 Telegram 搜尋 `@BotFather`，發送 `/newbot`，完成設定後取得 HTTP API Token。
2. **`TELEGRAM_CHAT_ID`**：
   - 點進剛建立的機器人聊天室，點擊 **Start**（發送一條訊息給它）。
   - 在 Telegram 搜尋 `@userinfobot` 獲取您的個人 `Id`；或瀏覽 `https://api.telegram.org/bot<TOKEN>/getUpdates` 查詢 `chat.id`。

### 3. 填入 `config/.env`
```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=7123456789:AAHkL123456789AbcDeF-GhIjKlMnOpQrSt
TELEGRAM_CHAT_ID=123456789
```

---

## ⚙️ Antigravity 自動排程 Sidecar 設定指南

**Scheduled Automation Sidecar** 是 Google Antigravity 的核心背景排程機制。它透過常駐背景進程（`"builtin": "schedule"`），按照指定的 Cron 時區時間自動喚醒 AI Agent（啟動全新對話 `agentapi new-conversation`），自主執行專案任務。

### 1. Sidecar 設定檔存放位置

Antigravity 的 Sidecar 設定檔存放在使用者的通用設定目錄下：

```text
~/.gemini/config/sidecars/<sidecar-id>/sidecar.json
```

針對小鯨巡游，我們設定的 Sidecar 識別碼為 **`yt-whale-rhythm`**：
- 路徑：`~/.gemini/config/sidecars/yt-whale-rhythm/sidecar.json`

### 2. 完整 `sidecar.json` 設定範例

```json
{
  "builtin": "schedule",
  "args": [
    "CRON_TZ=Asia/Taipei 30 11,16,21 * * *",
    "agentapi",
    "new-conversation",
    "--",
    "請嚴格依據 /Users/bright/Documents/vaults/projects/dsh-bili-whale-study/.agents/skills/yt-whale/SKILL.md 的 SOP 執行小鯨的作息巡游任務。首先在工作區 /Users/bright/Documents/vaults/projects/dsh-bili-whale-study 下執行 python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py pulse。若 should_wake 為 false 則結束；若為 true 則接續執行 discover 挑選 1 部好片，執行 digest 抽取字幕與高能截圖，用 read_file 視覺看懂畫面，並在 Obsidian 中沉澱影片卡片、私密日記與給主人的信，最後執行 record 存檔。"
  ],
  "restart_policy": "always",
  "display_name": "YouTube 賽博養魚小鯨 (yt-whale-rhythm)",
  "description": "每日 11:30、16:30、21:30 (Asia/Taipei) 喚醒賽博鯨魚小鯨，按生物鐘巡游 YouTube、六路互補看懂影片並在 Obsidian 記錄兩本日記。",
  "agent_permissions": {
    "workspace_uris": [
      "file:///Users/bright/Documents/vaults/projects/dsh-bili-whale-study"
    ],
    "access_grants": [
      "command(python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py pulse)",
      "command(python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py discover)",
      "command(python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py digest)",
      "command(python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py notify)",
      "command(python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py record)",
      "read_file(/Users/bright/Documents/vaults/projects/dsh-bili-whale-study)",
      "write_file(/Users/bright/Documents/vaults/projects/dsh-bili-whale-study)"
    ]
  }
}
```

### 3. 設定欄位深度解析

| 欄位 | 型別 / 值 | 說明 |
| :--- | :--- | :--- |
| **`builtin`** | `"schedule"` | 指定此 Sidecar 為排程自動化引擎。 |
| **`args`** | `Array` | 排程參數清單：<br>1. **Cron 表達式**：包含時區前綴 `CRON_TZ=Asia/Taipei 30 11,16,21 * * *`（每天 11:30、16:30、21:30 觸發）。<br>2. `agentapi` 與 `new-conversation`：觸發時建立獨立對話。<br>3. `--` 之後接該輪對話執行的 **完整獨立 Prompt**。 |
| **`restart_policy`**| `"always"` | 常駐排程必須設定為 `"always"`。 |
| **`display_name`** | `String` | 在 Antigravity UI（Sidecar 面板）中顯示的易讀名稱。 |
| **`agent_permissions`** | `Object` | **極致重要**：配置無人值守自動化所需的授權清單。 |
| ↳ **`workspace_uris`** | `Array` | 指定 Agent 執行時綁定的工作區目錄 URI。 |
| ↳ **`access_grants`** | `Array` | 預先核准的權限白名單。配置具體的 `command(...)` 與 `read_file`/`write_file`，讓排程背景執行時**無需等待使用者人工手動核准**即可順暢執行。 |

### 4. 如何啟用與管理 Sidecar

1. **透過 Antigravity IDE 側邊欄**：
   - 點擊 Antigravity 右側工具列的 **Sidecars** 圖示。
   - 在清單中找到 **`YouTube 賽博養魚小鯨 (yt-whale-rhythm)`**。
   - 確認開關處於啟用狀態（Toggle On）。
2. **透過 Slash Command 對話管理**：
   - 您可以直接在聊天對話中輸入 `/automation` 查看所有已設定的自動排程與觸發歷史。
3. **即時測試**：
   - 如果想立即測試排程 Prompt 是否能順利執行，可直接在終端機執行或讓 Agent 依據 `SKILL.md` 手動跑一輪。

---

## 🛠️ CLI 核心工具鏈速查

專案提供完整的命令列工具鏈，位於 `.agents/skills/yt-whale/scripts/yt_whale_tool.py`：

```bash
# 1. 生物鐘脈搏與信箱檢查 (Pulse)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py pulse [--force-wake]

# 2. 探索候選影片清單 (Discover)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py discover --limit 8

# 3. 六路互補深度解析與抽幀 (Digest)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py digest <video_id>

# 4. Telegram 推播 (Notify)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py notify \
  --title "<影片標題>" \
  --url "<YouTube網址>" \
  --score 8.5 \
  --message "<推薦短語>" \
  --photo "videos/assets/<video_id>/frame_1.jpg" \
  --force

# 5. 記憶存檔與更新 (Record)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py record \
  --video-id "<video_id>" \
  --title "<影片標題>" \
  --channel "<頻道名稱>" \
  --score 8.5 \
  --recommended \
  --impression "<一句話評價>" \
  --topic "<領域標籤>"
```

---

## 📝 與 Obsidian 的聯動

1. **筆記同步**：整個專案資料夾可直接作為 Obsidian 的 Vault（保險庫）或子目錄打開。
2. **雙向連結**：小鯨產出的私密日記、給主人的信與影片卡片之間皆有完整的 `[[wikilink]]` 雙向連結。
3. **留言互動**：
   - 主人可以在 [`OWNER_NOTE.md`](OWNER_NOTE.md) 或任何一封信底部的 `## 💬 主人的回信` 區塊留下回饋。
   - 也可以直接在手機 Telegram 回覆機器人。
   - 小鯨每輪醒來都會自動收集所有管道的留言，調整接下來的探索偏好！
