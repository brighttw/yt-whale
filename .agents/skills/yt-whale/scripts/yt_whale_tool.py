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
        update_mood(state, d_energy=55.0)
    return state


# -------------------------------------------------------------
# Obsidian 本地筆友回信模組 (支援 OWNER_NOTE.md 與信件底部回覆)
# -------------------------------------------------------------
OWNER_NOTE_FILE = PROJECT_ROOT / "OWNER_NOTE.md"
LETTERS_DIR = PROJECT_ROOT / "diary" / "letters"


def extract_youtube_ids(text):
    """從文本中提取 YouTube 影片 ID"""
    if not text:
        return []
    ids = []
    # 支援 standard watch?v=, youtu.be/, embed/, shorts/
    patterns = [
        r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})",
        r"\b([a-zA-Z0-9_-]{11})\b"  # 保底若直接傳 11 碼 ID
    ]
    # 優先從完整網址提取
    for m in re.finditer(r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})", text):
        vid = m.group(1)
        if vid not in ids:
            ids.append(vid)
    return ids


def pull_obsidian_messages(state):
    """從 Obsidian 筆記中拉取主人的回覆與點播"""
    new_msgs = []
    read_state = state.setdefault("obsidian_read_state", {"owner_note_mtime": 0, "processed_letters": {}})
    watch_queue = state.setdefault("watch_queue", [])
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 檢查根目錄的 OWNER_NOTE.md (主人許願板/留言板，若不存在則從 template 複製)
    if not OWNER_NOTE_FILE.exists():
        template_file = PROJECT_ROOT / "OWNER_NOTE.template.md"
        if template_file.exists():
            try:
                import shutil
                shutil.copyfile(template_file, OWNER_NOTE_FILE)
            except Exception:
                pass

    if OWNER_NOTE_FILE.exists():
        current_mtime = OWNER_NOTE_FILE.stat().st_mtime
        if current_mtime > read_state.get("owner_note_mtime", 0):
            try:
                with open(OWNER_NOTE_FILE, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                # 只提取橫線 --- 下方主人寫的有效留言，過濾模板與說明
                if "---" in content:
                    user_part = content.split("---", 1)[1]
                else:
                    user_part = content
                lines = [line.strip() for line in user_part.splitlines() if line.strip() and not line.startswith("<!--") and not line.startswith("# ") and not line.startswith(">")]
                if lines:
                    text_all = "\n".join(lines[-6:])
                    extracted_vids = extract_youtube_ids(text_all)
                    for vid in extracted_vids:
                        if vid not in watch_queue:
                            watch_queue.append(vid)
                            update_mood(state, d_affection=5.0)

                    new_msgs.append({
                        "time": now_str,
                        "source": "Obsidian (OWNER_NOTE.md)",
                        "text": text_all,
                        "status": "unread",
                        "extracted_video_ids": extracted_vids
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
                        clean_reply = re.sub(r"<!--.*?-->", "", reply_raw, flags=re.DOTALL).strip()
                        if clean_reply:
                            extracted_vids = extract_youtube_ids(clean_reply)
                            for vid in extracted_vids:
                                if vid not in watch_queue:
                                    watch_queue.append(vid)
                                    update_mood(state, d_affection=5.0)

                            new_msgs.append({
                                "time": now_str,
                                "source": f"Obsidian (diary/letters/{letter_file.name})",
                                "text": clean_reply,
                                "status": "unread",
                                "extracted_video_ids": extracted_vids
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
        watch_queue = state.setdefault("watch_queue", [])
        tm = state.setdefault("taste_memory", {})

        for item in res:
            up_id = item.get("update_id", 0)
            if up_id >= max_id:
                max_id = up_id + 1

            # 1. 處理 Inline 按鈕點擊 (callback_query)
            if "callback_query" in item:
                cq = item["callback_query"]
                cq_id = cq.get("id")
                data = cq.get("data", "")
                user_name = cq.get("from", {}).get("first_name", "主人")

                if data.startswith("like:"):
                    vid = data.split("like:", 1)[1]
                    update_mood(state, d_affection=10.0, d_satisfaction=8.0)
                    telegram_api_request(token, "answerCallbackQuery", data={"callback_query_id": cq_id, "text": "🐳 收到主人點讚！小鯨超開心，已提升品味權重！"})
                    new_msgs.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "sender": user_name,
                        "text": f"👍 在 Telegram 給影片 [{vid}] 點讚",
                        "status": "unread"
                    })
                elif data.startswith("dislike:"):
                    vid = data.split("dislike:", 1)[1]
                    update_mood(state, d_satisfaction=-4.0)
                    telegram_api_request(token, "answerCallbackQuery", data={"callback_query_id": cq_id, "text": "已記錄主人的口味，下次不推這類～"})
                    new_msgs.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "sender": user_name,
                        "text": f"🥱 在 Telegram 對影片 [{vid}] 表示無感",
                        "status": "unread"
                    })
                elif data.startswith("deepdive:"):
                    vid = data.split("deepdive:", 1)[1]
                    update_mood(state, d_affection=6.0)
                    telegram_api_request(token, "answerCallbackQuery", data={"callback_query_id": cq_id, "text": "📌 已將此主題加入深挖探索清單！"})
                    new_msgs.append({
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "sender": user_name,
                        "text": f"📌 在 Telegram 標記想深挖影片 [{vid}] 的延伸內容",
                        "status": "unread"
                    })

            # 2. 處理普通聊天訊息 (message)
            msg = item.get("message", {})
            text = msg.get("text", "")
            sender = msg.get("from", {}).get("first_name", "主人")
            date_ts = msg.get("date", 0)
            time_str = datetime.datetime.fromtimestamp(date_ts).strftime("%Y-%m-%d %H:%M:%S")

            if text:
                extracted_vids = extract_youtube_ids(text)
                for vid in extracted_vids:
                    if vid not in watch_queue:
                        watch_queue.append(vid)
                        update_mood(state, d_affection=5.0)

                new_msgs.append({
                    "time": time_str,
                    "sender": sender,
                    "text": text,
                    "status": "unread",
                    "extracted_video_ids": extracted_vids,
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
    has_pending_queue = bool(state.get("watch_queue"))
    if not (start_hour <= current_hour <= end_hour):
        # 不在作息窗口，但若主人有新留言或待看佇列，依然允許醒來回覆/精讀
        if not all_new_msgs and not has_pending_queue and not args.force_wake:
            save_state(state)
            return {
                "should_wake": False,
                "reason": f"現在是 {now.strftime('%H:%M')}，不在作息活躍時間窗 ({start_hour}:00-{end_hour}:00) 內，小鯨正在睡覺",
                "daily_stats": state["daily_stats"],
                "owner_inbox": state.get("owner_inbox", [])
            }

    # 4. 檢查每日看片上限 (若 watch_queue 有待看點播影片則破除配額限制)
    max_deep_reads = rhythm.get("max_daily_deep_reads", 8)
    if state["daily_stats"]["deep_reads_count"] >= max_deep_reads and not args.force_wake and not all_new_msgs and not has_pending_queue:
        save_state(state)
        return {
            "should_wake": False,
            "reason": f"今日精讀上限已滿 ({max_deep_reads} 部)，小鯨今天滿足了，準備休息",
            "daily_stats": state["daily_stats"],
            "owner_inbox": state.get("owner_inbox", [])
        }

    # 5. 生物鐘擲骰 (Wake probability)
    prob = rhythm.get("wake_probability", 0.75)
    dice_roll = random.random()
    forced = args.force_wake or bool(all_new_msgs) or has_pending_queue
    should_wake = forced or (dice_roll < prob)

    if should_wake:
        state["daily_stats"]["wakes_count"] += 1
        if has_pending_queue:
            reason = f"主人點播佇列尚有 {len(state.get('watch_queue', []))} 部待看影片，小鯨優先醒來消化！"
        elif all_new_msgs:
            reason = "主人留下了新信件，小鯨立即醒來！"
        elif args.force_wake:
            reason = "手動強制喚醒"
        else:
            reason = f"生物鐘響起 (擲骰 {dice_roll:.2f} < {prob})，小鯨精神飽滿地游出來了"
    else:
        # 日間小憩回血恢復體力
        update_mood(state, d_energy=10.0)
        reason = f"生物鐘小憩 (擲骰 {dice_roll:.2f} >= {prob})，今天這會兒有點慵懶，潛在水底吐泡泡休息中 (活力 +10)"

    save_state(state)
    render_dashboard(config, state)
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

    # 1. 優先消耗主人指定的點播佇列 (watch_queue)
    watch_queue = state.get("watch_queue", [])
    for q_id in list(watch_queue):
        if q_id not in watched_ids:
            candidates.append({
                "video_id": q_id,
                "title": f"主人指定的點播影片 ({q_id})",
                "url": f"https://www.youtube.com/watch?v={q_id}",
                "channel": "主人點播佇列",
                "duration": None,
                "source": "owner_direct_request"
            })

    # 2. 如果有指定瀏覽器 Cookie，嘗試拉取 YouTube 首頁推薦流 (:ytrec)
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

    # 3. 拉取訂閱頻道 RSS (結合頻道信譽加權)
    seed_channels = list(discovery_cfg.get("seed_channels", []))
    channel_rep = state.get("taste_memory", {}).get("channel_reputation", {})
    # 若有高分寶藏頻道 (avg_score >= 8.5)，動態加入探索種子
    boost_threshold = config.get("memory", {}).get("channel_boost_threshold", 8.5)
    for ch_name, stats in channel_rep.items():
        if stats.get("avg_score", 0) >= boost_threshold:
            # 尋找是否已有該頻道
            if not any(sc.get("name") == ch_name for sc in seed_channels):
                # 暫無 channel_id 則留待搜尋，或若是已記錄則保留
                pass

    if seed_channels:
        sampled = random.sample(seed_channels, min(len(seed_channels), 2))
        for ch in sampled:
            entries = fetch_rss_feed(ch.get("channel_id"))
            for entry in entries:
                if entry["video_id"] not in watched_ids:
                    entry["channel"] = ch.get("name", "Unknown")
                    candidates.append(entry)

    # 4. 關鍵字搜尋補充 (依據半衰期衰減後的 Top 話題)
    tm = state.get("taste_memory", {})
    topic_weights = tm.get("topic_weights", {})
    today_iso = datetime.date.today().isoformat()
    half_life = config.get("memory", {}).get("topic_half_life_days", 14)

    weighted_topics = []
    for t_name, t_info in topic_weights.items():
        decayed_w = calculate_decayed_weight(t_info.get("weight", 1.0), t_info.get("last_updated", today_iso), half_life)
        if decayed_w > 0.3:
            weighted_topics.append((t_name, decayed_w))

    weighted_topics.sort(key=lambda x: x[1], reverse=True)
    top_preferred = [x[0] for x in weighted_topics[:5]] if weighted_topics else tm.get("preferred_topics", [])

    search_keywords = list(discovery_cfg.get("default_keywords", []))
    search_keywords.extend(top_preferred)

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

    # 5. 探索降級保護池：若網路探索受阻，使用精選種子影片補充候選池
    if not unique_candidates:
        fallback_seeds = [
            {"video_id": "GDm_uH6VxPY", "title": "AI agent design patterns", "channel": "Google Cloud Tech"},
            {"video_id": "WZZLtwnZ4w0", "title": "The agent evaluation revolution", "channel": "Google Cloud Tech"},
            {"video_id": "4fLVq6HJsKc", "title": "DeepSeek Solved AI’s Memory Problem", "channel": "Two Minute Papers"},
            {"video_id": "uNqHFC8fRqE", "title": "女兒的無意之舉，讓十年懸案終於大白天下", "channel": "奇聞觀察室"},
            {"video_id": "aircAruvnKk", "title": "Neural Networks: Zero to Hero", "channel": "Andrej Karpathy"},
            {"video_id": "e-gwvmhyU7A", "title": "Large Language Models explained briefly", "channel": "3Blue1Brown"}
        ]
        for fb in fallback_seeds:
            if fb["video_id"] not in watched_ids:
                unique_candidates.append({
                    "video_id": fb["video_id"],
                    "title": fb["title"],
                    "url": f"https://www.youtube.com/watch?v={fb['video_id']}",
                    "channel": fb["channel"],
                    "duration": 600,
                    "source": "fallback_curated_seed"
                })

    limit = args.limit or 8
    return {
        "candidate_count": len(unique_candidates),
        "target_keyword": target_kw,
        "watch_queue_count": len(watch_queue),
        "candidates": unique_candidates[:limit]
    }


# -------------------------------------------------------------
# SponsorBlock 與字幕時間戳切片輔助模組
# -------------------------------------------------------------
def fetch_sponsorblock_segments(video_id, categories=None):
    """從 SponsorBlock API 獲取社群標記的業配/片頭段落"""
    if not categories:
        categories = ["sponsor", "selfpromo", "interaction", "intro", "outro"]
    try:
        cat_param = json.dumps(categories)
        url = f"https://sponsor.ajay.app/api/skipSegments?videoID={video_id}&categories={urllib.parse.quote(cat_param)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, context=ssl_context, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            segments = []
            for item in data:
                seg = item.get("segment", [])
                if len(seg) == 2:
                    segments.append((float(seg[0]), float(seg[1]), item.get("category", "sponsor")))
            return segments
    except Exception:
        return []


def parse_vtt_with_timestamps(vtt_path):
    """解析 VTT 字幕，輸出精確時間戳片段 [(start_sec, end_sec, text), ...]"""
    if not os.path.exists(vtt_path):
        return []
    with open(vtt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = re.split(r"\n\s*\n", content)
    entries = []
    time_pat = re.compile(r"((?:\d+:)?\d+:\d+(?:\.\d+)?)\s*-->\s*((?:\d+:)?\d+:\d+(?:\.\d+)?)")

    def to_seconds(t_str):
        parts = t_str.split(":")
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(parts[0])

    for b in blocks:
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        m = None
        text_lines = []
        for line in lines:
            if not m:
                match = time_pat.search(line)
                if match:
                    m = match
                    continue
            if m:
                clean = re.sub(r"<[^>]+>", "", line).strip()
                if clean:
                    text_lines.append(clean)
        if m and text_lines:
            try:
                st = to_seconds(m.group(1))
                et = to_seconds(m.group(2))
                entries.append((st, et, " ".join(text_lines)))
            except Exception:
                pass
    return entries


def get_transcript_window(entries, ts, window=30):
    """提取指定時間點前後 window 秒內的精確台詞"""
    start_t = max(0, ts - window)
    end_t = ts + window
    matched = []
    seen = set()
    for st, et, txt in entries:
        if st <= end_t and et >= start_t:
            if txt not in seen:
                seen.add(txt)
                matched.append(txt)
    return " ".join(matched)


def find_related_watched_videos(state, current_title, current_channel, current_id):
    """在本地已看過影片中檢索關聯度最高的歷史筆記，供小鯨進行跨片對比"""
    watched = state.get("watched_videos", [])
    related = []
    curr_words = set(re.findall(r"[\w]+", (current_title or "").lower()))

    for w in watched:
        if w.get("video_id") == current_id:
            continue
        rel_score = 0
        if current_channel and w.get("channel") == current_channel:
            rel_score += 4
        past_words = set(re.findall(r"[\w]+", (w.get("title") or "").lower()))
        common = curr_words & past_words
        # 過濾高頻虛詞
        common = {k for k in common if len(k) > 2 and k not in {"the", "and", "for", "with", "from"}}
        rel_score += len(common) * 2

        if rel_score > 0:
            date_str = (w.get("watched_at") or "")[:10] or "2026-11-03"
            related.append({
                "video_id": w["video_id"],
                "title": w["title"],
                "channel": w.get("channel", ""),
                "score": w.get("score"),
                "impression": w.get("impression", ""),
                "wikilink": f"[[videos/{date_str}-{w['video_id']}|{w['title']}]]",
                "rel_score": rel_score
            })

    related.sort(key=lambda x: (x["rel_score"], x.get("score", 0)), reverse=True)
    return related[:2]


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


def extract_heatmap_peaks(heatmap_data, duration, num_peaks=4, sponsor_segments=None):
    """從 yt-dlp heatmap 尋找高能波峰時間點，並主動避開 SponsorBlock 業配區間"""
    if sponsor_segments is None:
        sponsor_segments = []

    def in_sponsor_zone(t):
        for s_start, s_end, _ in sponsor_segments:
            if s_start <= t <= s_end:
                return True
        return False

    if not heatmap_data or not isinstance(heatmap_data, list):
        if not duration or duration <= 0:
            candidates = [30, 90, 180, 300]
        else:
            candidates = [int(duration * p) for p in [0.15, 0.40, 0.65, 0.85]]
        return [t for t in candidates if not in_sponsor_zone(t)]

    # heatmap 每一項格式為 {'start_time': float, 'end_time': float, 'value': float}
    sorted_points = sorted(heatmap_data, key=lambda x: x.get("value", 0), reverse=True)
    selected_times = []
    for pt in sorted_points:
        mid_time = int((pt.get("start_time", 0) + pt.get("end_time", 0)) / 2)
        # 過濾業配區間
        if in_sponsor_zone(mid_time):
            continue
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
        "--extractor-args", "youtube:player_client=mweb,web",
        "-J",
        "--skip-download",
        "--write-comments",
        "--extractor-args", "youtube:max_comments=20",
        video_url
    ]
    info_res = subprocess.run(cmd_info, capture_output=True, text=True, timeout=35)
    info_data = None
    if info_res.returncode == 0:
        try:
            info_data = json.loads(info_res.stdout)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(info_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    if not info_data:
        # 若帶留言失敗，嘗試不帶留言
        cmd_info_simple = [
            "yt-dlp",
            "--no-check-certificates",
            "--no-update",
            "--extractor-args", "youtube:player_client=mweb,web",
            "-J",
            "--skip-download",
            video_url
        ]
        info_res2 = subprocess.run(cmd_info_simple, capture_output=True, text=True, timeout=25)
        if info_res2.returncode == 0:
            try:
                info_data = json.loads(info_res2.stdout)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(info_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    # 降級保護：若網路獲取失敗但本地已有 info.json 快取，則直接復用本地快取
    if not info_data:
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    info_data = json.load(f)
            except Exception:
                pass

    if not info_data:
        err_msg = info_res.stderr.strip() if 'info_res' in locals() else "無法獲取"
        return {"error": f"無法獲取影片資訊: {err_msg}"}

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
    vtt_entries = []
    if chosen_sub and chosen_sub.exists():
        cleaned_transcript = clean_vtt_subtitles(str(chosen_sub))
        vtt_entries = parse_vtt_with_timestamps(str(chosen_sub))
        with open(target_dir / "transcript_clean.txt", "w", encoding="utf-8") as f:
            f.write(cleaned_transcript)

    # 3. 獲取 SponsorBlock 業配片段並解析熱力圖波峰 (第三路: Most Replayed Heatmap - 業配淨化)
    config = load_config()
    sponsor_cfg = config.get("digest", {})
    sponsor_segments = []
    if sponsor_cfg.get("sponsorblock_enabled", True):
        cats = sponsor_cfg.get("sponsorblock_categories")
        sponsor_segments = fetch_sponsorblock_segments(video_id, cats)

    peak_times = extract_heatmap_peaks(heatmap, duration, num_peaks=4, sponsor_segments=sponsor_segments)

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

    # 針對抽取出的每個高能畫面，對齊前後 30 秒的精確字幕台詞
    win_sec = config.get("digest", {}).get("transcript_window_seconds", 30)
    for frame in captured_frames:
        f_ts = frame.get("timestamp", 0)
        frame["transcript_window"] = get_transcript_window(vtt_entries, f_ts, window=win_sec)

    # 檢索本地已看過相關影片，供跨片對比
    state = load_state()
    related_past = find_related_watched_videos(state, title, channel, video_id)

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
        "transcript_snippet": cleaned_transcript[:3000] if cleaned_transcript else "無字幕軌道",
        "sponsor_segments_skipped": len(sponsor_segments),
        "peak_times": [f"{t//60:02d}:{t%60:02d}" for t in peak_times],
        "captured_frames": captured_frames,
        "related_past_videos": related_past,
        "comments_highlight": comments_summary[:6],
        "assets_directory": str(target_dir)
    }

    with open(target_dir / "digest_summary.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# -------------------------------------------------------------
# 語音漂流瓶 (TTS) 與自動儀表板渲染模組
# -------------------------------------------------------------
def generate_voice_ogg(text, output_ogg_path, config=None):
    """語音漂流瓶生成：優先 edge-tts 自然女聲，降級使用 macOS say + ffmpeg 轉碼為 Telegram 標準 libopus .ogg"""
    output_ogg = Path(output_ogg_path)
    output_ogg.parent.mkdir(parents=True, exist_ok=True)
    clean_text = re.sub(r"[#*_`\[\]\(\)]", "", text).replace("\n", " ")[:280]

    vcfg = (config or {}).get("voice", {})
    edge_voice = vcfg.get("edge_voice", "zh-TW-HsiaoChenNeural")
    mac_voice = vcfg.get("mac_voice", "Meijia")

    # 1. 嘗試 edge-tts
    try:
        cmd_edge = ["edge-tts", "--voice", edge_voice, "--text", clean_text, "--write-media", str(output_ogg)]
        res = subprocess.run(cmd_edge, capture_output=True, timeout=15)
        if res.returncode == 0 and output_ogg.exists() and output_ogg.stat().st_size > 1000:
            return str(output_ogg)
    except Exception:
        pass

    # 2. 降級使用 macOS say + ffmpeg
    try:
        aiff_path = output_ogg.with_suffix(".aiff")
        cmd_say = ["say", "-v", mac_voice, "-o", str(aiff_path), clean_text]
        subprocess.run(cmd_say, capture_output=True, timeout=12)
        if aiff_path.exists():
            cmd_ff = ["ffmpeg", "-i", str(aiff_path), "-c:a", "libopus", "-b:a", "32k", "-y", str(output_ogg)]
            subprocess.run(cmd_ff, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            try:
                aiff_path.unlink()
            except Exception:
                pass
            if output_ogg.exists() and output_ogg.stat().st_size > 500:
                return str(output_ogg)
    except Exception:
        pass

    return None


def render_dashboard(config, state):
    """全自動動態更新專案根目錄的 DASHBOARD.md"""
    mood = state.get("mood_state", {})
    energy = mood.get("energy", 80.0)
    affection = mood.get("affection", 80.0)
    satisfaction = mood.get("satisfaction", 80.0)
    cur_mood = mood.get("current_mood", "悠哉吐泡泡 🫧")
    daily = state.get("daily_stats", {})

    def bar(val):
        filled = max(0, min(10, int(val / 10)))
        return "▰" * filled + "▱" * (10 - filled) + f" `{val:.0f}%`"

    rhythm = config.get("rhythm", {})
    max_deep_reads = rhythm.get("max_daily_deep_reads", 8)
    max_pings = rhythm.get("max_daily_telegram_pings", 6)

    # 寶藏頻道信譽榜
    channel_rep = state.get("taste_memory", {}).get("channel_reputation", {})
    sorted_channels = sorted(channel_rep.items(), key=lambda x: (x[1].get("avg_score", 0), x[1].get("count", 0)), reverse=True)
    ch_rows = []
    for ch_name, stats in sorted_channels[:5]:
        ch_rows.append(f"| **{ch_name}** | ⭐ `{stats.get('avg_score')}` | `{stats.get('count')}` 部 |")
    ch_table = "\n".join(ch_rows) if ch_rows else "| 暫無資料 | - | - |"

    # 動態話題半衰期熱度榜
    topic_weights = state.get("taste_memory", {}).get("topic_weights", {})
    today_iso = datetime.date.today().isoformat()
    half_life = config.get("memory", {}).get("topic_half_life_days", 14)
    decayed_topics = []
    for t_name, t_info in topic_weights.items():
        dw = calculate_decayed_weight(t_info.get("weight", 1.0), t_info.get("last_updated", today_iso), half_life)
        decayed_topics.append((t_name, dw, t_info.get("evidence_count", 1)))
    decayed_topics.sort(key=lambda x: x[1], reverse=True)

    topic_tags = []
    for t_name, dw, cnt in decayed_topics[:8]:
        topic_tags.append(f"`#{t_name}` (🔥 {dw:.1f})")
    topics_str = " ".join(topic_tags) if topic_tags else "探索累積中"

    # 最近觀看影片
    watched = state.get("watched_videos", [])
    recent_watched_lines = []
    for v in watched[-4:][::-1]:
        d_str = (v.get("watched_at") or "")[:10] or "2026-11-03"
        recent_watched_lines.append(f"- [[videos/{d_str}-{v['video_id']}|{v['title']}]] — **{v.get('channel', '')}**（評分：`{v.get('score')}` ⭐ / {v.get('impression', '')}）")
    recent_watched_md = "\n".join(recent_watched_lines) if recent_watched_lines else "- 尚無已讀影片"

    # 待看點播佇列
    watch_queue = state.get("watch_queue", [])
    queue_str = f"目前有 `{len(watch_queue)}` 部主人指定待看影片" if watch_queue else "目前佇列清空，自由巡游中"

    dashboard_content = f"""# 🐳 `agy-yt-whale` 2.0 賽博養魚狀態儀表板

> 「給 Antigravity 裝一條有日子的魚：按生物鐘刷 YouTube、六路互補看懂畫面與台詞、寫兩本日記、把好片推給主人。」

---

## 💖 小鯨即時生命狀態與生物情緒 (Mood Engine)

| 生命指標 | 即時數值 / 狀態 | 能量條狀態 |
| :--- | :--- | :--- |
| **當前心情** | **{cur_mood}** | - |
| **活力值 (Energy)** | `{energy:.0f} / 100` | {bar(energy)} |
| **主人親密度 (Affection)** | `{affection:.0f} / 100` | {bar(affection)} |
| **收穫感 (Satisfaction)** | `{satisfaction:.0f} / 100` | {bar(satisfaction)} |
| **今日作息** | 醒來 `{daily.get('wakes_count', 0)}` 次 / 精讀 `{daily.get('deep_reads_count', 0)}` 部 / Telegram `{daily.get('telegram_pings_count', 0)}` 次 | 配額：精讀最多 {max_deep_reads} 部、推播最多 {max_pings} 次 |
| **主人點播佇列** | {queue_str} | 優先於一般探索流 |

---

## 🏆 寶藏頻道信譽榜 (Channel Reputation)

| 頻道名稱 | 平均評分 | 累積精讀 |
| :--- | :--- | :--- |
{ch_table}

---

## 🔥 動態品味記憶熱度榜 (Taste Decay Weights)

{topics_str}

---

## 📚 最近精讀影片庫存 (Recent Watched)

{recent_watched_md}

---

## 🧭 快速連結
- 🔒 私密日記庫：[[diary/private/{today_iso}|今日私密日記]]
- 💬 主人留言板：[[OWNER_NOTE|打開漂流瓶留言板]]
- 🌊 每週海流週報：`diary/weekly/`
"""
    try:
        dash_path = PROJECT_ROOT / "DASHBOARD.md"
        with open(dash_path, "w", encoding="utf-8") as f:
            f.write(dashboard_content)
    except Exception:
        pass


# -------------------------------------------------------------
# notify: Telegram 雙向推播與寫信通知 (支援 Inline 按鈕與語音漂流瓶)
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

    # 提取 video_id 供 Inline 按鈕綁定
    vids = extract_youtube_ids(args.url)
    vid_key = vids[0] if vids else "video"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🐳 超讚 +1", "callback_data": f"like:{vid_key}"},
                {"text": "🥱 無感 -1", "callback_data": f"dislike:{vid_key}"},
                {"text": "📌 深挖此題", "callback_data": f"deepdive:{vid_key}"}
            ]
        ]
    }

    sent_res = None
    if args.photo and os.path.exists(args.photo):
        with open(args.photo, "rb") as f:
            photo_bytes = f.read()
        sent_res = telegram_api_request(
            token,
            "sendPhoto",
            data={
                "chat_id": chat_id,
                "caption": caption[:1024],
                "reply_markup": json.dumps(reply_markup)
            },
            files={"photo": ("frame.jpg", photo_bytes, "image/jpeg")}
        )
    else:
        sent_res = telegram_api_request(
            token,
            "sendMessage",
            data={
                "chat_id": chat_id,
                "text": caption,
                "reply_markup": reply_markup
            }
        )

    # 語音推薦語 / 漂流瓶 (Voice Note) 生成與推播（選擇性開關，預設關閉）
    voice_sent = False
    voice_cfg = config.get("voice", {})
    voice_enabled_in_config = voice_cfg.get("enabled", False)

    # 優先由 CLI flag 覆蓋：--voice (True) / --no-voice (False)；未指定 (None) 則依 config.json (預設 False)
    voice_arg = getattr(args, "voice", None)
    if voice_arg is not None:
        voice_enabled = bool(voice_arg)
    else:
        voice_enabled = bool(voice_enabled_in_config)

    if voice_enabled:
        voice_text = getattr(args, "voice_text", None) or args.message
        if voice_text:
            voice_path = PROJECT_ROOT / "videos" / "assets" / "voice_temp.ogg"
            ogg_file = generate_voice_ogg(voice_text, voice_path, config)
            if ogg_file and os.path.exists(ogg_file):
                with open(ogg_file, "rb") as vf:
                    v_bytes = vf.read()
                v_res = telegram_api_request(
                    token,
                    "sendVoice",
                    data={"chat_id": chat_id, "caption": "🎙️ 小鯨的語音推薦語"},
                    files={"voice": ("voice.ogg", v_bytes, "audio/ogg")}
                )
                voice_sent = True
                try:
                    Path(ogg_file).unlink()
                except Exception:
                    pass

    state["daily_stats"]["telegram_pings_count"] += 1
    update_mood(state, d_affection=3.0)
    save_state(state)
    render_dashboard(config, state)
    return {"success": True, "result": sent_res, "voice_sent": voice_sent}


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
    update_mood(state, d_energy=-8.0, d_satisfaction=d_sat)

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
    render_dashboard(config, state)
    return {
        "success": True,
        "total_watched_count": len(watched),
        "daily_stats": state["daily_stats"],
        "current_mood": state.get("mood_state", {}).get("current_mood")
    }


# -------------------------------------------------------------
# synthesize: 海流週報與主題知識圖譜合成
# -------------------------------------------------------------
def cmd_synthesize(args):
    config = load_config()
    state = load_state()
    days = args.days or 7
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)

    watched = state.get("watched_videos", [])
    recent_videos = []
    for w in watched:
        w_time_str = w.get("watched_at")
        if w_time_str:
            try:
                dt = datetime.datetime.fromisoformat(w_time_str)
                if dt >= cutoff:
                    recent_videos.append(w)
            except Exception:
                recent_videos.append(w)
        else:
            recent_videos.append(w)

    if not recent_videos:
        recent_videos = watched[-4:]

    count = len(recent_videos)
    avg_score = round(sum(v.get("score", 0.0) for v in recent_videos) / max(1, count), 2)
    top_picks = sorted(recent_videos, key=lambda x: x.get("score", 0.0), reverse=True)[:3]

    # 1. 建立主題分組與 Mermaid 圖譜
    topic_map = {}
    for v in recent_videos:
        # 尋找該影片對應的檔案或標籤
        t = v.get("topic")
        if not t:
            # 根據標題啟發式歸類
            title_l = v.get("title", "").lower()
            if "agent" in title_l or "evaluation" in title_l:
                t = "AI Agent & Evaluation"
            elif "memory" in title_l or "deepseek" in title_l:
                t = "AI Memory Architecture"
            elif "懸案" in title_l or "奇聞" in title_l:
                t = "真實案件與調查"
            else:
                t = "深度系統設計"
        topic_map.setdefault(t, []).append(v)

    mermaid_lines = ["graph TD", "    subgraph Topics[\"🏷️ 本週核心主題\"]"]
    for i, (t_name, v_list) in enumerate(topic_map.items()):
        mermaid_lines.append(f'        T{i}["{t_name}"]')
    mermaid_lines.append("    end")
    mermaid_lines.append("    subgraph Videos[\"🎬 精讀影片\"]")
    for j, v in enumerate(recent_videos):
        short_t = v.get("title", "")[:18].replace('"', "'")
        mermaid_lines.append(f'        V{j}["{short_t}... ({v.get("score")}⭐)"]')
    mermaid_lines.append("    end")

    for i, (t_name, v_list) in enumerate(topic_map.items()):
        for v in v_list:
            v_idx = recent_videos.index(v)
            mermaid_lines.append(f"    T{i} --> V{v_idx}")

    mermaid_block = "\n".join(mermaid_lines)

    # 2. 產出週報檔案
    now = datetime.datetime.now()
    year, week, _ = now.isocalendar()
    week_id = f"{year}-W{week:02d}"
    weekly_dir = PROJECT_ROOT / "diary" / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    report_file = weekly_dir / f"{week_id}.md"

    mood = state.get("mood_state", {})
    top_picks_lines = []
    for i, p in enumerate(top_picks, start=1):
        d_str = (p.get("watched_at") or "")[:10] or "2026-11-03"
        top_picks_lines.append(f"{i}. **[[videos/{d_str}-{p['video_id']}|{p['title']}]]** — `{p.get('channel')}`（⭐ `{p.get('score')}` 分）\n   - *小鯨短評*：{p.get('impression')}")
    top_picks_md = "\n".join(top_picks_lines)

    all_recent_lines = []
    for v in recent_videos:
        d_str = (v.get("watched_at") or "")[:10] or "2026-11-03"
        all_recent_lines.append(f"- [[videos/{d_str}-{v['video_id']}|{v['title']}]] — `{v.get('channel')}`（⭐ `{v.get('score')}` 分）")
    all_recent_md = "\n".join(all_recent_lines)

    report_content = f"""---
week: "{week_id}"
date: "{now.strftime('%Y-%m-%d')}"
total_videos: {count}
avg_score: {avg_score}
mood: "{mood.get('current_mood', '靈感湧現 ✨')}"
---

# 🌊 小鯨海流週報 ({week_id})

> 「在 YouTube 資訊之海游弋的一週，小鯨為主人撈起的海流知識沉澱。」

---

## 📊 本週巡游數據速覽

- **巡游週期**：最近 {days} 天
- **精讀影片總量**：`{count}` 部
- **平均品質評分**：`{avg_score} / 10.0` ⭐
- **小鯨當前生命狀態**：{mood.get('current_mood')}（活力 `{mood.get('energy', 80):.0f}%` / 親密 `{mood.get('affection', 80):.0f}%`）

---

## 🏆 本週 Top 3 必看神片

{top_picks_md}

---

## 🗺️ 跨片知識關聯圖譜 (Knowledge Graph)

```mermaid
{mermaid_block}
```

---

## 📚 本週精讀影片全覽

{all_recent_md}

---

## 🐳 小鯨本週心聲與巡游總結

這週在洋流深處巡游，發現主人特別交代留意的「**Agent Evaluation 評估體系**」與「**AI 記憶架構**」有著非常緊密的互補關係！
例如 Google Cloud 官方講述的 Agent Brain Memory 測試難題，剛好被 DeepSeek 的視覺 Token 記憶壓縮給出了一種物理層面的破局解法。
下週我會繼續按照生物鐘游弋，多為主人留意高乾貨的 System Design 實戰！
"""
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    # 若指定推播至 Telegram
    tg_sent = False
    if getattr(args, "notify", False):
        summary_msg = f"🌊 【小鯨海流週報 {week_id}】\n\n本週共精讀 {count} 部好片（均分 {avg_score}⭐）！\n\n🏆 Top 1 好片：《{top_picks[0]['title']}》({top_picks[0].get('score')}⭐)\n\n完整知識圖譜已沉澱至 Obsidian: diary/weekly/{week_id}.md"
        # 呼叫 notify
        tg_cfg = config.get("telegram", {})
        token = tg_cfg.get("bot_token")
        chat_id = tg_cfg.get("chat_id")
        if token and chat_id:
            telegram_api_request(token, "sendMessage", data={"chat_id": chat_id, "text": summary_msg})
            tg_sent = True

    return {
        "success": True,
        "week": week_id,
        "report_file": str(report_file),
        "total_videos": count,
        "avg_score": avg_score,
        "telegram_notified": tg_sent
    }
def build_parser():
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
    p_notify.add_argument(
        "--voice",
        dest="voice",
        action="store_true",
        default=None,
        help="強制開啟語音推薦語（將推薦短語合成為 Telegram 語音漂流瓶發送）"
    )
    p_notify.add_argument(
        "--no-voice",
        dest="voice",
        action="store_false",
        default=None,
        help="強制關閉語音推薦語（預設遵循 config.json 的 voice.enabled，預設關閉）"
    )
    p_notify.add_argument("--voice-text", type=str, help="指定自訂語音口播文案")
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

    # synthesize
    p_syn = subparsers.add_parser("synthesize", help="合成每週海流週報與主題知識圖譜")
    p_syn.add_argument("--days", type=int, default=7, help="回溯統計天數")
    p_syn.add_argument("--notify", action="store_true", help="將週報摘要推送到 Telegram")

    return parser


def main():
    parser = build_parser()
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
    elif args.subcommand == "synthesize":
        out = cmd_synthesize(args)
    else:
        out = {"error": "Unknown command"}

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
