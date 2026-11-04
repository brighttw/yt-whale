# 🐳 `agy-yt-whale` 2.0：YouTube 賽博養魚小鯨

> 「給 Google Antigravity 裝一條有日子的魚：按生物鐘巡游 YouTube、六路互補看懂畫面與台詞、擁有三維生物情緒、寫 Obsidian 雙本日記與海流週報、用 Telegram 雙向互動與語音漂流瓶陪伴主人。」

---

## 📖 專案簡介 (What's New in 2.0)

`agy-yt-whale` 2.0 是一個基於 **Google Antigravity** 與 **Obsidian** 的全自主數位生命與知識伴侶專案。
對標並深度融合了中文社群著名的 **DSH 大肥魚生態**（`dsh-bili-whale`、`dsh-feiyu-mood`、`dsh-fish-memory`）以及現代知識管理工具（`SponsorBlock`、`NotebookLM`、`Readwise`），實現了全面的 2.0 進化：

- 💖 **三維生物情緒引擎 (Mood Engine 2.0)**：
  - 追蹤「活力 `energy`、主人親密度 `affection`、收穫感 `satisfaction`」三維指數與時間半衰期。
  - 精讀影片消耗體力、休息恢復、踩雷低分片吐槽、受到主人誇獎開心加倍，情緒動態注入小鯨的寫作與互動語氣。
- 🧠 **智慧品味記憶與寶藏頻道信譽榜**：
  - 話題自帶時間半衰期衰減模型（$W(t) = W_0 \cdot 0.5^{\Delta t / 14}$），避免無效膨脹。
  - 自動維護頻道信譽榜（平均分與精讀次數），高分頻道自動升格為種子探索流。
- 🎬 **六路互補深度解析 2.0 (SponsorBlock + 圖文聲對齊)**：
  - 整合 **SponsorBlock API**，自動跳過片頭廢話與商業業配，避免高能抽幀踩雷。
  - **精準台詞窗口對齊 (Peak-Aligned Transcript Windows)**：每個截圖自動關聯前後 30 秒的精確字幕台詞。
  - **跨片記憶共鳴 (Cross-Video Recall)**：自動比對本地看過的舊片，在筆記中生成跨片深度對比。
- 📱 **Telegram 全閉環雙向互動與語音漂流瓶**：
  - **Inline 互動按鈕**：推播附帶 `[🐳 超讚 +1]`、`[🥱 無感 -1]`、`[📌 深挖]`，手機一鍵反饋並即時回饋品味權重。
  - **點播連結提取**：在 Telegram 或 Obsidian 丟 YouTube 連結，自動排入優先待看佇列 `watch_queue`。
  - **語音漂流瓶 (Voice Note)**：透過 TTS（Edge-TTS 自然女聲 / macOS 原生 `say` + `ffmpeg` libopus 保底）發送 Telegram 語音推薦語（支援選擇性開關，**預設關閉**）。
- 🌊 **每週海流週報與主題知識圖譜 (Synthesize)**：
  - 支援一鍵/排程彙整近 7 天精讀筆記、Top 3 必看神片與 Mermaid 主題關聯圖譜至 `diary/weekly/`。
- 📊 **全自動狀態儀表板渲染器**：每次脈搏檢查與存檔，全自動重繪 [DASHBOARD.md](DASHBOARD.md)。

---

## 📂 專案目錄結構

```text
dsh-bili-whale-study/
├── .agents/
│   └── skills/
│       └── yt-whale/              # Antigravity 技能定義與工具鏈
│           ├── SKILL.md           # 核心 SOP 2.0 操作手冊
│           └── scripts/
│               └── yt_whale_tool.py # 核心 Python 工具鏈 (pulse/discover/digest/notify/record/synthesize)
├── config/
│   ├── config.json                # 通用行為設定檔（人設、作息、半衰期、語音等）
│   ├── env.example                # 環境變數範本（可視版）
│   └── .env                       # ⚠️ 真正的機密設定檔（受 .gitignore 隔離）
├── diary/
│   ├── private/                   # 小鯨私密日記（寫給自己，附帶情緒狀態）
│   ├── letters/                   # 給主人的信（推薦好片）
│   └── weekly/                    # 🌊 小鯨每週海流週報（含 Mermaid 知識圖譜）
├── videos/
│   ├── assets/<video_id>/         # 影片關鍵幀截圖、台詞窗口、digest_summary.json、info.json
│   └── YYYY-MM-DD-<video_id>.md   # 結構化影片深讀卡片（含跨片關聯）
├── state/
│   └── whale_state.json           # V2 狀態庫（三維情緒、品味半衰期、頻道信譽、必看佇列）
├── DASHBOARD.md                   # 📊 全自動動態渲染狀態儀表板
├── OWNER_NOTE.md                  # 💬 主人漂流瓶留言板（支援 YT 網址點播）
└── README.md                      # 專案說明文件
```

---

## 🛠️ CLI 核心工具鏈速查 (2.0)

專案提供完整的命令列工具鏈，位於 `.agents/skills/yt-whale/scripts/yt_whale_tool.py`：

```bash
# 1. 生物鐘脈搏檢查 (Pulse: 包含情緒推導、信箱已讀與自動更新儀表板)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py pulse [--force-wake]

# 2. 探索候選影片清單 (Discover: 優先消耗點播佇列 + 寶藏頻道加權)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py discover --limit 8

# 3. 六路互補深度解析 2.0 (Digest: SponsorBlock 去業配 + 波峰台詞對齊 + 跨片關聯)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py digest <video_id>

# 4. Telegram 互動推播 (Notify: 附帶 Inline 按鈕，語音推薦語可選)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py notify \
  --title "<影片標題>" \
  --url "<YouTube網址>" \
  --score 8.5 \
  --message "<推薦短語>" \
  --photo "videos/assets/<video_id>/frame_1.jpg"
  # 可選開關語音：加 --voice 強制開啟，或加 --no-voice 強制關閉（預設遵循 config.json）

# 5. 記憶存檔與儀表板重繪 (Record: 更新三維情緒、頻道信譽、主題權重半衰期)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py record \
  --video-id "<video_id>" \
  --title "<影片標題>" \
  --channel "<頻道名稱>" \
  --score 8.5 \
  --recommended \
  --impression "<一句話評價>" \
  --topic "<領域標籤>"

# 6. 每週海流週報合成 (Synthesize: 跨片知識關聯圖譜 + Top 3 評選)
python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py synthesize --days 7 [--notify]
```

---

## 🎙️ 語音推薦語（語音漂流瓶）功能與開關指南

小鯨具備將影片推薦短語轉換為 Telegram 語音訊息（Voice Note 漂流瓶）的功能，支援 Edge-TTS 自然女聲（預設 `zh-TW-HsiaoChenNeural`）及 macOS 本地 `say` + `ffmpeg` libopus 保底合成。

> 💡 **預設狀態說明**：考量到不同用戶對語音播放的使用習慣與合成效果偏好，**語音推薦語功能預設為關閉 (`disabled`)**。你可以隨時透過以下兩種方式自由選擇性開關：

### 1. 全域設定檔開關（推薦）
在 [`config/config.json`](config/config.json) 中的 `voice` 區塊設定：
```json
"voice": {
  "enabled": false,               // true: 開啟語音推薦語；false: 關閉（預設）
  "tts_engine": "auto",           // auto / edge / mac
  "edge_voice": "zh-TW-HsiaoChenNeural", // Edge-TTS 自然音色
  "mac_voice": "Meijia"           // macOS 本地保底音色
}
```
- **關閉語音（預設）**：將 `"enabled": false`。推播時僅發送文字卡片與精采關鍵幀截圖，不產生任何音訊。
- **開啟語音**：將 `"enabled": true`。小鯨在 Telegram 推播時會自動合成語音短評並以語音氣泡發送。

### 2. 單次 CLI 命令列覆蓋
若需要臨時開啟或強制跳過語音，可直接在 `notify` 指令加上參數：
- **強制開啟語音**：加上 `--voice`
  ```bash
  python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py notify \
    --title "影片標題" --url "https://..." --score 8.5 --message "推薦短語" --voice
  ```
- **強制關閉語音**：加上 `--no-voice`
  ```bash
  python3 .agents/skills/yt-whale/scripts/yt_whale_tool.py notify \
    --title "影片標題" --url "https://..." --score 8.5 --message "推薦短語" --no-voice
  ```
- **自訂口播文字**：加上 `--voice-text "<自訂語音文字>"` 指定與文字卡片不同的語音講稿。
- **未傳入參數**：自動依循 `config/config.json` 的 `voice.enabled` 設定（預設關閉）。

---

## ⚙️ Antigravity 自動排程 Sidecar 設定

小鯨的自動作息由常駐排程 Sidecar（`~/.gemini/config/sidecars/yt-whale-rhythm/sidecar.json`）驅動：
- **Cron 時區**：`CRON_TZ=Asia/Taipei 0 9,12,15,18,21 * * *`
- **權限白名單**：已配置無人值守執行的 `pulse`、`discover`、`digest`、`notify`、`record` 與 `synthesize` 命令授權。

---

## 📝 與 Obsidian 的全閉環聯動

1. **雙向筆友交流**：
   - 在 [`OWNER_NOTE.md`](OWNER_NOTE.md) 或任何信件底部的 `## 💬 主人的回信` 寫下回饋或直接貼上 YouTube 連結。
   - 小鯨下次醒來自動識別並排入必看佇列，同時增加與主人的親密度！
2. **視覺化儀表板**：
   - 隨時打開 [`DASHBOARD.md`](DASHBOARD.md) 查看小鯨的三維情緒能量條、寶藏頻道榜與品味話題。
3. **每週海流知識沉澱**：
   - 打開 [`diary/weekly/`](diary/weekly/) 查閱每週生成的 Mermaid 主題圖譜與跨片關聯報告。
