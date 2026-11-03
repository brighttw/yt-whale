#!/usr/bin/env python3
"""
yt_whale_tool.py
YouTube 版「賽博養魚」核心工具鏈。
提供生物鐘 (pulse)、探索 (discover)、六路解析 (digest)、推播 (notify)、記憶存檔 (record) 等功能。
"""

import argparse
import datetime
import json
import math
import os
import random
import re
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# 略過本機過期/缺失之 CA 憑證驗證
ssl_context = ssl._create_unverified_context()

# 路徑定位
PROJECT_ROOT = Path(__file__).resolve().parents[4]
CONFIG_FILE = PROJECT_ROOT / "config" / "config.json"
ENV_FILE = PROJECT_ROOT / "config" / ".env"
STATE_FILE = PROJECT_ROOT / "state" / "whale_state.json"
ASSETS_DIR = PROJECT_ROOT / "videos" / "assets"


def load_config():
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 讀取 .env 中的 Telegram 配置（若存在）
    if ENV_FILE.exists():
        env_content = ENV_FILE.read_text(encoding="utf-8")
        for line in env_content.splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                val = line.split("=", 1)[1].strip()
                if val:
                    config.setdefault("telegram", {})["bot_token"] = val
            elif line.startswith("TELEGRAM_CHAT_ID="):
                val = line.split("=", 1)[1].strip()
                if val:
                    config.setdefault("telegram", {})["chat_id"] = val
            elif line.startswith("TELEGRAM_ENABLED="):
                val = line.split("=", 1)[1].strip().lower()
                config.setdefault("telegram", {})["enabled"] = val in ("true", "1", "yes")

        # 若 .env 提供了有效 Token，預設自動啟用 Telegram 功能（除非明確指定 TELEGRAM_ENABLED=false）
        tg = config.setdefault("telegram", {})
        if tg.get("bot_token") and tg.get("chat_id") and "TELEGRAM_ENABLED=" not in env_content:
            tg["enabled"] = True
    return config


def migrate_state_v2(state, config=None):
    """將狀態無損遷移至 V2：包含三維情緒、半衰期品味權重、頻道信譽與必看佇列"""
    now_iso = datetime.datetime.now().isoformat()
    today_iso = datetime.date.today().isoformat()

    # 1. 三維情緒模型
    mood = state.setdefault("mood_state", {
        "energy": 85.0,
        "affection": 80.0,
        "satisfaction": 80.0,
        "current_mood": "靈感湧現 ✨",
        "last_mood_update": now_iso
    })
    if "current_mood" not in mood:
        mood["current_mood"] = derive_mood(mood)

    # 2. 優先必看佇列
    state.setdefault("watch_queue", [])

    # 3. 升級品味記憶
    tm = state.setdefault("taste_memory", {})
    topic_weights = tm.setdefault("topic_weights", {})
    channel_rep = tm.setdefault("channel_reputation", {})

    for topic in tm.get("preferred_topics", []):
        if topic not in topic_weights:
            topic_weights[topic] = {
                "weight": 2.0,
                "last_updated": today_iso,
                "evidence_count": 1
            }

    # 回填已觀看影片的頻道信譽
    if not channel_rep:
        for v in state.get("watched_videos", []):
            ch = v.get("channel")
            score = v.get("score", 8.0)
            if ch:
                rec = channel_rep.setdefault(ch, {"total_score": 0.0, "count": 0, "avg_score": 0.0})
                rec["total_score"] += score
                rec["count"] += 1
                rec["avg_score"] = round(rec["total_score"] / rec["count"], 2)

    return state


def calculate_decayed_weight(initial_weight, last_updated_iso, half_life_days=14):
    """依時間半衰期計算話題權重：W(t) = W0 * 0.5^(dt / half_life)"""
    try:
        last_dt = datetime.datetime.fromisoformat(last_updated_iso).date()
        today = datetime.date.today()
        days_passed = max(0, (today - last_dt).days)
        decay = math.pow(0.5, days_passed / max(1, half_life_days))
        return round(initial_weight * decay, 3)
    except Exception:
        return initial_weight


def derive_mood(mood):
    """根據三維指數推導即時心情標籤"""
    energy = mood.get("energy", 80)
    affection = mood.get("affection", 80)
    satisfaction = mood.get("satisfaction", 80)

    if energy < 30:
        return "電力不足想睡覺 💤"
    if affection >= 90:
        return "被主人寵愛超開心 💖"
    if satisfaction >= 85:
        return "靈感湧現 ✨"
    if satisfaction < 60:
        return "踩雷小傲嬌 💢"
    return "悠哉吐泡泡 🫧"


def update_mood(state, d_energy=0.0, d_affection=0.0, d_satisfaction=0.0):
    """更新情緒指數並確保數值在 0~100 之間"""
    mood = state.setdefault("mood_state", {
        "energy": 85.0,
        "affection": 80.0,
        "satisfaction": 80.0,
        "current_mood": "靈感湧現 ✨",
        "last_mood_update": datetime.datetime.now().isoformat()
    })
    mood["energy"] = max(0.0, min(100.0, round(mood.get("energy", 80.0) + d_energy, 1)))
    mood["affection"] = max(0.0, min(100.0, round(mood.get("affection", 80.0) + d_affection, 1)))
    mood["satisfaction"] = max(0.0, min(100.0, round(mood.get("satisfaction", 80.0) + d_satisfaction, 1)))
    mood["current_mood"] = derive_mood(mood)
    mood["last_mood_update"] = datetime.datetime.now().isoformat()
    return mood


def load_state():
    if not STATE_FILE.exists():
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        init_state = {
            "last_pulse_time": None,
            "daily_stats": {"date": None, "wakes_count": 0, "deep_reads_count": 0, "telegram_pings_count": 0},
            "telegram_offset": 0,
            "owner_inbox": [],
            "watched_videos": [],
            "taste_memory": {"preferred_topics": [], "disliked_topics": [], "shared_memories": []},
            "cooldown_until": None,
        }
        return migrate_state_v2(init_state)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
        return migrate_state_v2(st)


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_daily_reset(state):
    today_str = datetime.date.today().isoformat()
    daily = state.get("daily_stats", {})
    if daily.get("date") != today_str:
        state["daily_stats"] = {
            "date": today_str,
            "wakes_count": 0,
            "deep_reads_count": 0,
            "telegram_pings_count": 0,
        }
        # 新的一天恢復體力
        update_mood(state, d_energy=30.0)
    return state


# -------------------------------------------------------------
# Obsidian 本地筆友回信模組 (支援 OWNER_NOTE.md 與信件底部回覆)
# -------------------------------------------------------------
OWNER_NOTE_FILE = PROJECT_ROOT / "OWNER_NOTE.md"
LETTERS_DIR = PROJECT_ROOT / "diary" / "letters"


def pull_obsidian_messages(state):
    """從 Obsidian 筆記中拉取主人的回覆與點播"""
    new_msgs = []
    read_state = state.setdefault("obsidian_read_state", {"owner_note_mtime": 0, "processed_letters": {}})
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 檢查根目錄的 OWNER_NOTE.md (主人許願板/留言板)
    if OWNER_NOTE_FILE.exists():
        current_mtime = OWNER_NOTE_FILE.stat().st_mtime
        if current_mtime > read_state.get("owner_note_mtime", 0):
            try:
                with open(OWNER_NOTE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                # 簡單過濾模板說明文字，只提取主人寫的有效留言
                lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("<!--") and not line.startswith("# ")]
                if lines:
                    new_msgs.append({
                        "time": now_str,
                        "source": "Obsidian (OWNER_NOTE.md)",
                        "text": "\n".join(lines[-6:])  # 最新幾行
                    })
                read_state["owner_note_mtime"] = current_mtime
            except Exception:
                pass

    # 2. 檢查 diary/letters/ 下每一封信件底部是否有「## 💬 主人的回信」
    if LETTERS_DIR.exists():
        processed_letters = read_state.setdefault("processed_letters", {})
        for letter_file in LETTERS_DIR.glob("*.md"):
            try:
                file_mtime = letter_file.stat().st_mtime
                last_mtime = processed_letters.get(letter_file.name, 0)
                if file_mtime > last_mtime:
                    with open(letter_file, "r", encoding="utf-8") as f:
                        text = f.read()
                    # 尋找回信標題
                    match = re.search(r"##\s+(?:💬\s*)?(?:主人的?回信|主人回覆)(.*?)(?=$|\n##)", text, re.DOTALL | re.IGNORECASE)
                    if match:
                        reply_raw = match.group(1).strip()
                        # 移除 HTML 註解 <!-- ... -->
                        clean_reply = re.sub(r"<!--.*?-->", "", reply_raw, flags=re.DOTALL).strip()
                        if clean_reply:
                            new_msgs.append({
                                "time": now_str,
                                "source": f"Obsidian (diary/letters/{letter_file.name})",
                                "text": clean_reply
                            })
                    processed_letters[letter_file.name] = file_mtime
            except Exception:
                pass

    if new_msgs:
        state.setdefault("owner_inbox", []).extend(new_msgs)
    return new_msgs


# -------------------------------------------------------------
# Telegram 整合模組 (無狀態長輪詢與訊息推播)
# -------------------------------------------------------------
def telegram_api_request(token, method, params=None, data=None, files=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    if files:
        boundary = f"----WebKitFormBoundary{random.randint(1000000, 9999999)}"
        body = bytearray()
        for key, val in (data or {}).items():
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode("utf-8"))
        for field_name, (filename, file_bytes, mime) in files.items():
            body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"))
            body.extend(file_bytes)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode("utf-8"))
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.data = bytes(body)
    elif data:
        json_data = json.dumps(data).encode("utf-8")
        req.add_header("Content-Type", "application/json")
        req.data = json_data

    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return res.get("result", None)
    except Exception as e:
        return {"error": str(e)}


def pull_telegram_messages(config, state):
    tg_cfg = config.get("telegram", {})
    token = tg_cfg.get("bot_token")
    if not token or not tg_cfg.get("enabled", True):
        return []

    offset = state.get("telegram_offset", 0)
    res = telegram_api_request(token, "getUpdates", params={"offset": offset, "timeout": 2})
    if isinstance(res, list):
        new_msgs = []
        max_id = offset
        for item in res:
            up_id = item.get("update_id", 0)
            if up_id >= max_id:
                max_id = up_id + 1
            msg = item.get("message", {})
            text = msg.get("text", "")
            sender = msg.get("from", {}).get("first_name", "主人")
            date_ts = msg.get("date", 0)
            time_str = datetime.datetime.fromtimestamp(date_ts).strftime("%Y-%m-%d %H:%M:%S")
            if text:
                new_msgs.append({
                    "time": time_str,
                    "sender": sender,
                    "text": text,
                    "chat_id": msg.get("chat", {}).get("id")
                })
        state["telegram_offset"] = max_id
        if new_msgs:
            state.setdefault("owner_inbox", []).extend(new_msgs)
        return new_msgs
    return []


# -------------------------------------------------------------
# pulse: 生物鐘脈搏檢查
# -------------------------------------------------------------
def cmd_pulse(args):
    config = load_config()
    state = load_state()
    state = check_daily_reset(state)

    now = datetime.datetime.now()
    state["last_pulse_time"] = now.isoformat()

    # 1. 檢查主人的新留言 (雙通道: Obsidian 本地筆記 + Telegram 雲端信箱)
    new_obsidian_msgs = pull_obsidian_messages(state)
    new_telegram_msgs = pull_telegram_messages(config, state)
    all_new_msgs = new_obsidian_msgs + new_telegram_msgs

    # 2. 檢查風控冷卻期
    cooldown = state.get("cooldown_until")
    if cooldown:
        cd_time = datetime.datetime.fromisoformat(cooldown)
        if now < cd_time:
            save_state(state)
            return {
                "should_wake": False,
                "reason": f"處於風控冷卻期中，將於 {cooldown} 後恢復",
                "daily_stats": state["daily_stats"],
                "owner_inbox": state.get("owner_inbox", [])
            }

    # 3. 檢查作息窗口 (active_hours)
    rhythm = config.get("rhythm", {})
    start_hour, end_hour = rhythm.get("active_hours", [9, 23])
    current_hour = now.hour
    if not (start_hour <= current_hour <= end_hour):
        # 不在作息窗口，但若主人有新留言，依然允許醒來回覆
        if not all_new_msgs and not args.force_wake:
            save_state(state)
            return {
                "should_wake": False,
                "reason": f"現在是 {now.strftime('%H:%M')}，不在作息活躍時間窗 ({start_hour}:00-{end_hour}:00) 內，小鯨正在睡覺",
                "daily_stats": state["daily_stats"],
                "owner_inbox": state.get("owner_inbox", [])
            }

    # 4. 檢查每日看片上限
    max_deep_reads = rhythm.get("max_daily_deep_reads", 4)
    if state["daily_stats"]["deep_reads_count"] >= max_deep_reads and not args.force_wake and not all_new_msgs:
        save_state(state)
        return {
            "should_wake": False,
            "reason": f"今日精讀上限已滿 ({max_deep_reads} 部)，小鯨今天滿足了，準備休息",
            "daily_stats": state["daily_stats"],
            "owner_inbox": state.get("owner_inbox", [])
        }

    # 5. 生物鐘擲骰 (Wake probability)
    prob = rhythm.get("wake_probability", 0.6)
    dice_roll = random.random()
    forced = args.force_wake or bool(all_new_msgs)
    should_wake = forced or (dice_roll < prob)

    if should_wake:
        state["daily_stats"]["wakes_count"] += 1
        reason = "主人留下了新信件，小鯨立即醒來！" if all_new_msgs else (
            "手動強制喚醒" if args.force_wake else f"生物鐘響起 (擲骰 {dice_roll:.2f} < {prob})，小鯨精神飽滿地游出來了"
        )
    else:
        reason = f"生物鐘小憩 (擲骰 {dice_roll:.2f} >= {prob})，今天這會兒有點慵懶，繼續潛在水底吐泡泡"

    save_state(state)
    mood = state.get("mood_state", {})
    return {
        "should_wake": should_wake,
        "reason": reason,
        "mood_state": mood,
        "mood_prompt_hint": f"目前小鯨心情為「{mood.get('current_mood')}」(活力:{mood.get('energy')}%, 親密:{mood.get('affection')}%, 滿足:{mood.get('satisfaction')}%)，在日記與給主人的信中請自然流露出此狀態",
        "daily_stats": state["daily_stats"],
        "owner_inbox": state.get("owner_inbox", [])[-5:],  # 最近 5 則
        "watch_queue": state.get("watch_queue", []),
        "new_messages_from_owner": all_new_msgs
    }


# -------------------------------------------------------------
# discover: 混合輕量探索流
# -------------------------------------------------------------
def fetch_rss_feed(channel_id):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ssl_context, timeout=8) as resp:
            content = resp.read()
            root = ET.fromstring(content)
            entries = []
            ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
            for entry in root.findall("atom:entry", ns):
                vid = entry.find("yt:videoId", ns)
                title = entry.find("atom:title", ns)
                published = entry.find("atom:published", ns)
                if vid is not None and title is not None:
                    entries.append({
                        "video_id": vid.text,
                        "title": title.text,
                        "url": f"https://www.youtube.com/watch?v={vid.text}",
                        "published": published.text if published is not None else "",
                        "source": "rss_channel"
                    })
            return entries
    except Exception:
        return []


def cmd_discover(args):
    config = load_config()
    state = load_state()
    watched_ids = {item["video_id"] for item in state.get("watched_videos", [])}

    discovery_cfg = config.get("discovery", {})
    browser = discovery_cfg.get("cookies_from_browser")
    candidates = []

    # 1. 如果有指定瀏覽器 Cookie，嘗試拉取 YouTube 首頁推薦流 (:ytrec)
    if browser:
        cmd = ["yt-dlp", "--no-check-certificates", "--no-update", "--cookies-from-browser", browser, "--flat-playlist", "-J", "--playlist-end", "10", ":ytrec"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for entry in data.get("entries", []):
                    vid = entry.get("id")
                    if vid and vid not in watched_ids:
                        candidates.append({
                            "video_id": vid,
                            "title": entry.get("title", ""),
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "channel": entry.get("channel", entry.get("uploader", "")),
                            "duration": entry.get("duration"),
                            "source": "youtube_recommendation"
                        })
        except Exception:
            pass

    # 2. 拉取訂閱頻道 RSS
    seed_channels = discovery_cfg.get("seed_channels", [])
    if seed_channels:
        # 隨機或輪流挑選 2 個種子頻道
        sampled = random.sample(seed_channels, min(len(seed_channels), 2))
        for ch in sampled:
            entries = fetch_rss_feed(ch.get("channel_id"))
            for entry in entries:
                if entry["video_id"] not in watched_ids:
                    entry["channel"] = ch.get("name", "Unknown")
                    candidates.append(entry)

    # 3. 關鍵字搜尋補充
    search_keywords = list(discovery_cfg.get("default_keywords", []))
    preferred = state.get("taste_memory", {}).get("preferred_topics", [])
    search_keywords.extend(preferred)

    if args.keyword:
        target_kw = args.keyword
    else:
        target_kw = random.choice(search_keywords) if search_keywords else "AI agent"

    search_query = f"ytsearch6:{target_kw}"
    cmd_search = ["yt-dlp", "--no-check-certificates", "--no-update", "--flat-playlist", "-J", search_query]
    try:
        res = subprocess.run(cmd_search, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            for entry in data.get("entries", []):
                vid = entry.get("id")
                if vid and vid not in watched_ids:
                    candidates.append({
                        "video_id": vid,
                        "title": entry.get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "channel": entry.get("channel", entry.get("uploader", "")),
                        "duration": entry.get("duration"),
                        "source": f"search:{target_kw}"
                    })
    except Exception:
        pass

    # 去重
    unique_candidates = []
    seen = set()
    for item in candidates:
        if item["video_id"] not in seen and item["video_id"] not in watched_ids:
            seen.add(item["video_id"])
            unique_candidates.append(item)

    limit = args.limit or 8
    return {
        "candidate_count": len(unique_candidates),
        "target_keyword": target_kw,
        "candidates": unique_candidates[:limit]
    }


# -------------------------------------------------------------
# digest: YouTube 六路互補解析 (含 Most Replayed 波峰與 ffmpeg 抽幀)
# -------------------------------------------------------------
def clean_vtt_subtitles(vtt_path):
    """清洗 VTT/SRT 字幕，去重時間戳與標籤，產出簡潔文本"""
    if not os.path.exists(vtt_path):
        return ""
    lines = []
    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 移除 WEBVTT 開頭、標籤與時間戳行
    raw_lines = content.splitlines()
    seen_texts = []
    for line in raw_lines:
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        # 移除 <c> 等 HTML 標籤
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and (not seen_texts or seen_texts[-1] != clean):
            seen_texts.append(clean)

    return "\n".join(seen_texts)


def extract_heatmap_peaks(heatmap_data, duration, num_peaks=4):
    """從 yt-dlp heatmap 尋找高能波峰時間點"""
    if not heatmap_data or not isinstance(heatmap_data, list):
        # 若無熱力圖，依照經驗黃金比例取點
        if not duration or duration <= 0:
            return [30, 90, 180, 300]
        return [int(duration * p) for p in [0.15, 0.40, 0.65, 0.85]]

    # heatmap 每一項格式為 {'start_time': float, 'end_time': float, 'value': float}
    sorted_points = sorted(heatmap_data, key=lambda x: x.get("value", 0), reverse=True)
    selected_times = []
    for pt in sorted_points:
        mid_time = int((pt.get("start_time", 0) + pt.get("end_time", 0)) / 2)
        # 確保選取的波峰之間至少間隔 40 秒，避免重複在同一小段抽幀
        if all(abs(mid_time - st) > 40 for st in selected_times):
            selected_times.append(mid_time)
            if len(selected_times) >= num_peaks:
                break

    selected_times.sort()
    return selected_times


def cmd_digest(args):
    raw_input = args.video_target.strip()
    # 支援傳入完整網址或純 ID
    if "v=" in raw_input:
        video_id = urllib.parse.parse_qs(urllib.parse.urlparse(raw_input).query).get("v", [""])[0]
    elif "youtu.be/" in raw_input:
        video_id = raw_input.split("youtu.be/")[1].split("?")[0]
    else:
        video_id = raw_input

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    target_dir = ASSETS_DIR / video_id
    target_dir.mkdir(parents=True, exist_ok=True)

    # 1. 抓取影片元數據 (第一路: Metadata + Chapters + Heatmap + 留言)
    json_path = target_dir / "info.json"
    cmd_info = [
        "yt-dlp",
        "--no-check-certificates",
        "--no-update",
        "-J",
        "--skip-download",
        "--write-comments",
        "--extractor-args", "youtube:max_comments=20",
        video_url
    ]
    info_res = subprocess.run(cmd_info, capture_output=True, text=True, timeout=35)
    if info_res.returncode != 0:
        # 若抓留言報錯，嘗試不帶留言純抓 info
        cmd_info_simple = ["yt-dlp", "--no-check-certificates", "--no-update", "-J", "--skip-download", video_url]
        info_res = subprocess.run(cmd_info_simple, capture_output=True, text=True, timeout=25)
        if info_res.returncode != 0:
            return {"error": f"無法獲取影片資訊: {info_res.stderr.strip()}"}

    info_data = json.loads(info_res.stdout)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(info_data, f, ensure_ascii=False, indent=2)

    title = info_data.get("title", "")
    channel = info_data.get("channel", info_data.get("uploader", ""))
    duration = info_data.get("duration", 0)
    description = info_data.get("description", "")
    chapters = info_data.get("chapters", [])
    heatmap = info_data.get("heatmap", [])

    # 2. 抓取字幕 (第二路: CC / Auto Subtitle)
    sub_prefix = str(target_dir / "sub")
    cmd_sub = [
        "yt-dlp",
        "--no-check-certificates",
        "--no-update",
        "--skip-download",
        "--write-sub",
        "--write-auto-sub",
        "--sub-lang", "zh-Hant,zh-Hans,en",
        "--sub-format", "vtt",
        "-o", sub_prefix,
        video_url
    ]
    subprocess.run(cmd_sub, capture_output=True, text=True, timeout=25)

    # 尋找下載好的字幕檔（優先度: zh-Hant > zh-Hans > en）
    vtt_candidates = list(target_dir.glob("sub*.vtt"))
    chosen_sub = None
    for pref in ["zh-Hant", "zh-Hans", "zh", "en"]:
        for f in vtt_candidates:
            if pref in f.name:
                chosen_sub = f
                break
        if chosen_sub:
            break
    if not chosen_sub and vtt_candidates:
        chosen_sub = vtt_candidates[0]

    cleaned_transcript = ""
    if chosen_sub and chosen_sub.exists():
        cleaned_transcript = clean_vtt_subtitles(str(chosen_sub))
        with open(target_dir / "transcript_clean.txt", "w", encoding="utf-8") as f:
            f.write(cleaned_transcript)

    # 3. 解析熱力圖波峰 (第三路: Most Replayed Heatmap)
    peak_times = extract_heatmap_peaks(heatmap, duration, num_peaks=4)

    # 4. 提取留言精選 (第四路: Comments & Timestamps)
    comments_summary = []
    raw_comments = info_data.get("comments", [])
    if raw_comments:
        for c in raw_comments[:15]:
            author = c.get("author", "觀眾")
            text = c.get("text", "")
            likes = c.get("like_count", 0)
            has_timestamp = bool(re.search(r"\b\d{1,2}:\d{2}\b", text))
            comments_summary.append({
                "author": author,
                "text": text,
                "likes": likes,
                "has_timestamp": has_timestamp
            })

    # 5. 精準高能畫面提取 (第五路: Keyframe Snapshots)
    # 策略 A（優先 HD 畫質）：使用 mweb client 抓取指定波峰秒數的 2 秒微片段 (僅 ~70KB)，ffmpeg 抽幀達到極高清文字辨識
    # 策略 B（降級保護）：若微片段下載失敗，自動退回 Storyboard 精靈圖或高清封面
    captured_frames = []

    for i, ts in enumerate(peak_times, start=1):
        frame_filename = f"frame_{i}.jpg"
        frame_path = target_dir / frame_filename
        clip_path = target_dir / f"clip_{i}.mp4"

        # 嘗試高畫質微片段抽幀
        start_sec = max(0, ts - 1)
        end_sec = ts + 1
        cmd_clip = [
            "yt-dlp",
            "--no-check-certificates",
            "--no-update",
            "--extractor-args", "youtube:player_client=mweb,web",
            "-f", "18/best[height<=720]/best",
            "--download-sections", f"*{start_sec}-{end_sec}",
            "-o", str(clip_path),
            video_url
        ]
        clip_res = subprocess.run(cmd_clip, capture_output=True, text=True, timeout=25)
        if clip_path.exists() and clip_path.stat().st_size > 1000:
            cmd_ff = [
                "ffmpeg",
                "-ss", "00:00:01",
                "-i", str(clip_path),
                "-frames:v", "1",
                "-q:v", "2",
                "-y",
                str(frame_path)
            ]
            subprocess.run(cmd_ff, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            # 清理 70KB 暫存影片
            try:
                clip_path.unlink()
            except Exception:
                pass

        if frame_path.exists() and frame_path.stat().st_size > 1000:
            captured_frames.append({
                "index": i,
                "timestamp": ts,
                "time_str": f"{ts//60:02d}:{ts%60:02d}",
                "file_path": str(frame_path),
                "relative_path": f"videos/assets/{video_id}/{frame_filename}",
                "source": "native_hd_stream"
            })

    # 若上述 HD 模式未產出足夠幀，啟動 Storyboard 精靈圖裁剪降級
    if len(captured_frames) < len(peak_times):
        sb_format = None
        for fmt_id in ["sb0", "sb1", "sb2"]:
            for fmt in info_data.get("formats", []):
                if fmt.get("format_id") == fmt_id and fmt.get("fragments"):
                    sb_format = fmt
                    break
            if sb_format:
                break

        if sb_format and sb_format.get("fragments"):
            fragments = sb_format["fragments"]
            frag_dur = fragments[0].get("duration", 44.0) or 44.0
            w, h, cols = 320, 180, 3

            for i, ts in enumerate(peak_times, start=1):
                frame_filename = f"frame_{i}.jpg"
                frame_path = target_dir / frame_filename
                if frame_path.exists() and frame_path.stat().st_size > 1000:
                    continue  # 已有 HD 幀

                frag_idx = min(int(ts / frag_dur), len(fragments) - 1)
                target_frag = fragments[frag_idx]
                frag_url = target_frag.get("url")
                offset_in_frag = ts % frag_dur
                frame_in_mosaic = min(int(offset_in_frag / (frag_dur / 9.0)), 8)
                crop_x = (frame_in_mosaic % cols) * w
                crop_y = (frame_in_mosaic // cols) * h

                mosaic_file = target_dir / f"mosaic_{frag_idx}.jpg"
                try:
                    if not mosaic_file.exists() and frag_url:
                        req = urllib.request.Request(frag_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, context=ssl_context, timeout=10) as r:
                            with open(mosaic_file, "wb") as mf:
                                mf.write(r.read())

                    if mosaic_file.exists():
                        cmd_ffmpeg = [
                            "ffmpeg",
                            "-i", str(mosaic_file),
                            "-vf", f"crop={w}:{h}:{crop_x}:{crop_y}",
                            "-q:v", "2",
                            "-y",
                            str(frame_path)
                        ]
                        subprocess.run(cmd_ffmpeg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                        if frame_path.exists():
                            captured_frames.append({
                                "index": i,
                                "timestamp": ts,
                                "time_str": f"{ts//60:02d}:{ts%60:02d}",
                                "file_path": str(frame_path),
                                "relative_path": f"videos/assets/{video_id}/{frame_filename}",
                                "source": "storyboard_fallback"
                            })
                except Exception:
                    pass

    # 降級保護：若無 storyboard，嘗試直接抓取影片最高清 Thumbnail
    if not captured_frames:
        thumb_url = info_data.get("thumbnail")
        if thumb_url:
            fallback_frame = target_dir / "frame_1.jpg"
            try:
                req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=ssl_context, timeout=10) as r:
                    with open(fallback_frame, "wb") as f:
                        f.write(r.read())
                captured_frames.append({
                    "index": 1,
                    "timestamp": 0,
                    "time_str": "00:00",
                    "file_path": str(fallback_frame),
                    "relative_path": f"videos/assets/{video_id}/frame_1.jpg"
                })
            except Exception:
                pass

    # 整理摘要回傳
    result = {
        "video_id": video_id,
        "url": video_url,
        "title": title,
        "channel": channel,
        "duration_seconds": duration,
        "duration_str": f"{duration//60}分{duration%60}秒",
        "chapters": chapters,
        "has_subtitles": bool(cleaned_transcript),
        "transcript_snippet": cleaned_transcript[:1200] if cleaned_transcript else "無字幕軌道",
        "peak_times": [f"{t//60:02d}:{t%60:02d}" for t in peak_times],
        "captured_frames": captured_frames,
        "comments_highlight": comments_summary[:6],
        "assets_directory": str(target_dir)
    }

    with open(target_dir / "digest_summary.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# -------------------------------------------------------------
# notify: Telegram 雙向推播與寫信通知
# -------------------------------------------------------------
def cmd_notify(args):
    config = load_config()
    state = load_state()
    state = check_daily_reset(state)

    rhythm = config.get("rhythm", {})
    max_pings = rhythm.get("max_daily_telegram_pings", 3)
    current_pings = state["daily_stats"]["telegram_pings_count"]

    if current_pings >= max_pings and not args.force:
        return {
            "success": False,
            "reason": f"今日 Telegram 推播次數已達上限 ({max_pings} 次)，已轉為僅寫入 Obsidian 日記，不打擾主人。"
        }

    tg_cfg = config.get("telegram", {})
    token = tg_cfg.get("bot_token")
    chat_id = tg_cfg.get("chat_id")

    if not token or not chat_id:
        return {
            "success": False,
            "reason": "尚未配置 Telegram Bot Token 或 Chat ID。通知已跳過，僅在本地 Obsidian 建立信件。"
        }

    caption = f"🐳 【小鯨好片分享】\n\n📺 《{args.title}》\n⭐ 評分：{args.score}/10\n\n💬 小鯨推薦語：\n{args.message}\n\n🔗 傳送門：{args.url}"

    sent_res = None
    if args.photo and os.path.exists(args.photo):
        with open(args.photo, "rb") as f:
            photo_bytes = f.read()
        sent_res = telegram_api_request(
            token,
            "sendPhoto",
            data={"chat_id": chat_id, "caption": caption[:1024]},
            files={"photo": ("frame.jpg", photo_bytes, "image/jpeg")}
        )
    else:
        sent_res = telegram_api_request(
            token,
            "sendMessage",
            data={"chat_id": chat_id, "text": caption}
        )

    state["daily_stats"]["telegram_pings_count"] += 1
    save_state(state)
    return {"success": True, "result": sent_res}


# -------------------------------------------------------------
# record: 狀態與品味記憶更新
# -------------------------------------------------------------
def cmd_record(args):
    config = load_config()
    state = load_state()
    state = check_daily_reset(state)

    watched = state.setdefault("watched_videos", [])
    watched.append({
        "video_id": args.video_id,
        "title": args.title,
        "channel": args.channel or "",
        "score": args.score,
        "recommended": args.recommended,
        "impression": args.impression or "",
        "watched_at": datetime.datetime.now().isoformat()
    })

    state["daily_stats"]["deep_reads_count"] += 1

    # 1. 精讀消耗活力，評分影響滿足感
    d_sat = 8.0 if args.score >= 8.5 else (-10.0 if args.score < 7.0 else 2.0)
    update_mood(state, d_energy=-12.0, d_satisfaction=d_sat)

    # 2. 如果影片在優先待看佇列中，完成後移出佇列
    if "watch_queue" in state and args.video_id in state["watch_queue"]:
        state["watch_queue"].remove(args.video_id)

    # 3. 更新話題權重與品味記憶 (半衰期模型)
    if args.topic:
        tm = state.setdefault("taste_memory", {})
        preferred = tm.setdefault("preferred_topics", [])
        if args.topic not in preferred:
            preferred.append(args.topic)

        topic_weights = tm.setdefault("topic_weights", {})
        today_iso = datetime.date.today().isoformat()
        half_life = config.get("memory", {}).get("topic_half_life_days", 14)

        if args.topic in topic_weights:
            item = topic_weights[args.topic]
            decayed = calculate_decayed_weight(item.get("weight", 1.0), item.get("last_updated", today_iso), half_life)
            boost = 1.0 if args.score >= 8.0 else 0.2
            item["weight"] = round(decayed + boost, 3)
            item["last_updated"] = today_iso
            item["evidence_count"] = item.get("evidence_count", 0) + 1
        else:
            topic_weights[args.topic] = {
                "weight": 2.0 if args.score >= 8.0 else 1.0,
                "last_updated": today_iso,
                "evidence_count": 1
            }

    # 4. 更新頻道信譽庫
    if args.channel:
        tm = state.setdefault("taste_memory", {})
        channel_rep = tm.setdefault("channel_reputation", {})
        ch_stat = channel_rep.setdefault(args.channel, {"total_score": 0.0, "count": 0, "avg_score": 0.0})
        ch_stat["total_score"] = round(ch_stat.get("total_score", 0.0) + args.score, 2)
        ch_stat["count"] = ch_stat.get("count", 0) + 1
        ch_stat["avg_score"] = round(ch_stat["total_score"] / ch_stat["count"], 2)

    # 演算法回饋：若啟用了瀏覽器 Cookie，在背景執行 mark-watched
    browser = config.get("discovery", {}).get("cookies_from_browser")
    if browser:
        video_url = f"https://www.youtube.com/watch?v={args.video_id}"
        subprocess.Popen(
            ["yt-dlp", "--no-check-certificates", "--no-update", "--cookies-from-browser", browser, "--mark-watched", "--skip-download", video_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    save_state(state)
    return {
        "success": True,
        "total_watched_count": len(watched),
        "daily_stats": state["daily_stats"]
    }


# -------------------------------------------------------------
# Main CLI 入口
# -------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="YouTube 版賽博養魚核心工具")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # pulse
    p_pulse = subparsers.add_parser("pulse", help="檢查生物鐘狀態與 Telegram 收信")
    p_pulse.add_argument("--force-wake", action="store_true", help="強制小鯨醒來")

    # discover
    p_discover = subparsers.add_parser("discover", help="探索與拉取候選影片清單")
    p_discover.add_argument("--keyword", type=str, help="指定搜尋關鍵字")
    p_discover.add_argument("--limit", type=int, default=8, help="候選數量")

    # digest
    p_digest = subparsers.add_parser("digest", help="YouTube 六路互補深度解析與抽幀")
    p_digest.add_argument("video_target", type=str, help="YouTube 影片網址或 ID")

    # notify
    p_notify = subparsers.add_parser("notify", help="發送 Telegram 推播通知")
    p_notify.add_argument("--title", type=str, required=True, help="影片標題")
    p_notify.add_argument("--url", type=str, required=True, help="影片網址")
    p_notify.add_argument("--score", type=float, required=True, help="評分")
    p_notify.add_argument("--message", type=str, required=True, help="推薦理由")
    p_notify.add_argument("--photo", type=str, help="關鍵幀截圖路徑")
    p_notify.add_argument("--force", action="store_true", help="忽略每日次數限制")

    # record
    p_record = subparsers.add_parser("record", help="記憶存檔與標記已讀")
    p_record.add_argument("--video-id", type=str, required=True, help="影片 ID")
    p_record.add_argument("--title", type=str, required=True, help="影片標題")
    p_record.add_argument("--channel", type=str, default="", help="頻道名稱")
    p_record.add_argument("--score", type=float, required=True, help="評分")
    p_record.add_argument("--recommended", action="store_true", help="是否推薦給主人")
    p_record.add_argument("--impression", type=str, default="", help="一句話短評")
    p_record.add_argument("--topic", type=str, help="關聯主題標籤")

    args = parser.parse_args()

    if args.subcommand == "pulse":
        out = cmd_pulse(args)
    elif args.subcommand == "discover":
        out = cmd_discover(args)
    elif args.subcommand == "digest":
        out = cmd_digest(args)
    elif args.subcommand == "notify":
        out = cmd_notify(args)
    elif args.subcommand == "record":
        out = cmd_record(args)
    else:
        out = {"error": "Unknown command"}

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
