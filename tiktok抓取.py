# -*- coding: utf-8 -*-
"""TikTok 账号发现：个人博主 + 访谈/多人采访。

不调用浏览器、不下载封面/视频。只走 tikwm 接口拿标签与用户作品元数据。
入选条件：同一账号至少有多条「正脸出镜」倾向的作品；文案尽量无水印/花边/烧录字幕；
访谈号还要求被访者出镜（嘉宾/对谈/点名 @ 等信号）。
"""
import os
import re
import time
import random
import sqlite3
import itertools
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from curl_cffi import requests as creq

# ==========================================
# ⚙️ 核心配置区
# ==========================================
TARGET_TOTAL_ACCOUNTS = 3400    # 已有约 400，再找 3000
EXPORT_BATCH_SIZE = 500
VIDEOS_PER_TAG = 30
PAGES_PER_TAG = 2
MIN_FACE_VIDEOS = 2             # 同一账号至少几条出镜作品
FETCH_WORKERS = 3
PROXY = "http://127.0.0.1:7897"
API_SEM = threading.Semaphore(2)
MUSIC_SNOWBALL_OK = True        # 拍同款（同原声）；接口若 403 会自动关掉

DB_PATH = "tiktok_accounts_meta.db"
OUTPUT_DIR = "./TikTok_Exports"
os.makedirs(OUTPUT_DIR, exist_ok=True)

TIKWM = "https://www.tikwm.com/api"
MIN_DUR_PERSONAL = 5
MAX_DUR_PERSONAL = 90
MIN_DUR_INTERVIEW = 15
MAX_DUR_INTERVIEW = 600

CORE_ROOTS = [
    "ballet", "ballerina", "pointe", "contemporarydance", "moderndance", "dancer",
    "opera", "soprano", "mezzo", "tenor", "baritone", "belcanto", "vocal", "choir",
    "selftape", "monologue", "audition", "actor", "actress", "theatreactor", "broadway",
    "violin", "violinist", "cello", "cellist", "pianist", "classicalguitar", "flutist",
    "harpist", "clarinet", "oboe", "orchestra", "symphony", "chambermusic",
    "figureskating", "iceskater", "rhythmicgymnastics", "gymnast", "acrobatics",
    "contortion", "handbalance", "handstand", "pilates", "ashtanga", "calisthenics",
    "modeldigitals", "compcard", "polaroids", "selfportrait", "headshot",
]

ACTION_MODIFIERS = [
    "", "practice", "rehearsal", "variation", "solo", "warmup", "training",
    "routine", "studio", "class", "improvisation", "session",
    "performance", "recital", "daily", "technique",
]

MULTILINGUAL_SEEDS = [
    "bailarina", "danza", "patinajeartistico", "cantantelirico", "violoncelo",
    "patinageartistique", "danseclassique", "chanteuse", "conservatoire",
    "ballett", "opernsänger", "kunstturnen", "eiskunstlauf",
    "балет", "балерина", "фигурноекатание", "художественнаягимнастика", "опера",
    "バレエ", "クラシックバレエ", "フィギュアスケート", "ヴァイオリン", "ピアノ練習",
    "발레", "성악", "바이올린", "피아노연습", "현대무용", "연기오디션",
]

INTERVIEW_ROOTS = [
    "podcast", "interview", "talkshow", "conversations", "sitdowninterview",
    "celebrityinterview", "streetinterview", "podcastclip", "inconversation",
    "guestinterview", "roundtable", "paneldiscussion", "artisttalk",
    "behindthescenesinterview", "podcastinterview", "livepodcast",
    "interviewpodcast", "talkshowclip", "couchinterview", "studiointerview",
    "podcastmoments", "podcasthighlights", "twopeoplepodcast",
    "entrevista", "entrevistapodcast", "インタビュー", "인터뷰", "интервью",
]

INTERVIEW_KEYWORDS = {
    "podcast", "interview", "talkshow", "talk show", "sit down", "sitdown",
    "in conversation", "inconversation", "guest", "roundtable", "panel",
    "entrevista", "インタビュー", "인터뷰", "интервью", "采访", "访谈", "播客",
}

# 嘉宾/被访者出镜信号
GUEST_ON_CAMERA = [
    "guest", "my guest", "our guest", "interview with", "sits down", "sit down with",
    "sitdown with", "in conversation with", "talking with", "chats with", "chat with",
    "featuring", "feat.", "ft.", "street interview", "man on the street",
    "采访", "嘉宾", "对谈", "访谈", "entrevista con", "with @",
]

# 无脸/纯音频/只有主持人口播
FACELESS_OR_AUDIO = [
    "faceless", "no face", "audio only", "audioonly", "voiceover", "voice over",
    "just listen", "listen to", "waveform", "spotify", "apple podcast",
]

SPAM_BLACKLIST = {
    "candle", "candles", "wax", "scent", "soap", "shop", "store", "boutique",
    "smallbusiness", "smallbiz", "etsy", "shopify", "amazon", "commission",
    "linkinbio", "link in bio", "discount", "coupon", "sale", "promo", "unboxing",
    "haul", "review", "tutorial", "how to", "howto", "tips", "pov", "storytime",
    "reddit", "lyrics", "lyricvideo", "duet", "duet with me", "stitch",
    "meme", "funny", "prank", "filter", "capcut", "greenscreen", "edit",
    "jobinterview", "interviewtips", "interviewprep", "careercoach", "careertok",
    "recruiter", "resume", "salary", "hiring", "jobsearch", "interviewhack",
    "common interview", "answer interview", "how to interview", "watermark",
    "subtitle", "captions", "closed caption", "text on screen", "lyric",
    "burned in", "on screen text", "overlay text", "animated text",
}

CHANNEL_INDICATORS = {
    "opera", "ballet", "theatre", "theater", "orchestra", "symphony", "philharmonic",
    "academy", "institute", "conservatory", "school", "club", "official", "museum",
    "center", "centre", "company", "foundation", "festival", "ensemble", "society",
    "network", "media", "radio", "channel",
}

NAME_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "your", "our", "new",
    "official", "dance", "dancer", "dancers", "ballet", "ballerina", "music",
    "video", "tiktok", "fyp", "foryou", "viral", "love", "best", "live",
    "studio", "class", "practice", "training", "performance", "recital",
    "podcast", "interview", "show", "clip", "moment", "daily", "watch",
} | CHANNEL_INDICATORS

_NAME_PREFIX = re.compile(
    r"(?:feat(?:uring)?\.?|ft\.?|with|starring|soloist|dancer|danced by|"
    r"performed by|guest|采访|嘉宾|主演|出镜|出演)\s+"
    r"(@?[A-Za-z][\w.'-]{1,20}(?:\s+[A-Z][a-z]{1,20}){0,2})",
    re.I,
)
_NAME_CAPS = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})\b")
_NAME_CJK = re.compile(r"(?:嘉宾|采访|主演|出镜|出演)[:：\s]*([\u4e00-\u9fff]{2,4})")
_AT_NAME = re.compile(r"@([A-Za-z][A-Za-z0-9._]{1,24})")

PRIORITY_TAGS = [
    "podcast", "interview", "talkshow", "conversations", "sitdowninterview",
    "celebrityinterview", "streetinterview", "podcastclip", "guestinterview",
    "roundtable", "entrevista", "ballet", "ballerina", "violin", "cello",
    "pianist", "figureskating", "opera", "dancer", "contemporarydance",
    "gymnast", "headshot", "broadway", "choir", "orchestra", "selftape",
]

_tls = threading.local()


def http_session():
    sess = getattr(_tls, "sess", None)
    if sess is None:
        sess = creq.Session()
        _tls.sess = sess
    return sess


def http_get(url, params=None, retries=4, timeout=40):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.tikwm.com/",
        "Origin": "https://www.tikwm.com",
    }
    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
    last = None
    with API_SEM:
        for i in range(retries):
            try:
                time.sleep(random.uniform(0.12, 0.35))
                r = http_session().get(
                    url, params=params, impersonate="chrome131",
                    timeout=timeout, proxies=proxies, headers=headers,
                )
                if r.status_code == 403:
                    return r
                return r
            except Exception as e:
                last = e
                time.sleep(1.2 + i)
    if hasattr(last, "status_code"):
        return last
    raise last


def generate_initial_tags():
    tags = set(MULTILINGUAL_SEEDS) | set(INTERVIEW_ROOTS) | set(PRIORITY_TAGS) | set(CORE_ROOTS)
    for root in CORE_ROOTS:
        for mod in ("practice", "rehearsal", "studio", "performance", "training"):
            combined = f"{root}{mod}".lower()
            if 3 <= len(combined) <= 35:
                tags.add(combined)
    return list(tags)


def is_interview_tag(tag_str):
    t = (tag_str or "").lower()
    if t in INTERVIEW_ROOTS:
        return True
    return any(k.replace(" ", "") in t.replace(" ", "") for k in INTERVIEW_KEYWORDS)


def is_safe_snowball_tag(tag_str):
    t = tag_str.lower()
    if len(t) < 4 or len(t) > 35:
        return False
    if any(bad in t for bad in SPAM_BLACKLIST):
        return False
    if any(root in t for root in CORE_ROOTS):
        return True
    return is_interview_tag(t)


def looks_spam(text, handle=""):
    blob = f"{text} {handle}".lower()
    return any(bad in blob for bad in SPAM_BLACKLIST)


def looks_overlay_heavy(text):
    t = (text or "").lower()
    return any(k in t for k in (
        "capcut", "subtitle", "captions", "lyrics", "lyric", "greenscreen",
        "text on screen", "on screen text", "watermark", "closed caption",
        "stitch", "duet",
    ))


def looks_faceless(text):
    t = (text or "").lower()
    return any(k in t for k in FACELESS_OR_AUDIO)


STRONG_GUEST_TAGS = {
    "sitdowninterview", "celebrityinterview", "streetinterview", "guestinterview",
    "roundtable", "paneldiscussion", "couchinterview", "studiointerview",
    "inconversation", "entrevista", "twopeoplepodcast",
}


def has_guest_on_camera(title, mentioned_users="", tag=""):
    t = (title or "").lower()
    if looks_faceless(t):
        return False
    tg = (tag or "").lower().replace(" ", "")
    if tg in STRONG_GUEST_TAGS or any(x in tg for x in ("sitdown", "streetinterview", "guest", "roundtable", "panel")):
        return True
    if mentioned_users and str(mentioned_users).strip() not in ("", "[]", "null"):
        return True
    if re.search(r"@[\w.]+", title or ""):
        return True
    return any(k in t for k in GUEST_ON_CAMERA)


def looks_like_person_name(s):
    s = re.sub(r"[#@]", "", (s or "")).strip(" .,-|·")
    if not s or len(s) < 2:
        return False
    low = s.lower()
    if low in NAME_STOP or any(w in low for w in ("official", "company", "academy")):
        return False
    parts = re.split(r"[\s._]+", s)
    parts = [p for p in parts if p]
    if not parts or len(parts) > 3:
        return False
    if any(p.lower() in NAME_STOP for p in parts):
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", s):
        return True
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 3


def extract_on_screen_name(title, bio="", nickname=""):
    blob = f"{title or ''} {bio or ''}"
    cands = []
    for rx in (_NAME_PREFIX, _NAME_CJK, _AT_NAME, _NAME_CAPS):
        cands.extend(rx.findall(blob) or [])
    if nickname:
        nick = re.sub(r"[^\w\s\u4e00-\u9fff.'-]", " ", nickname).strip()
        if looks_like_person_name(nick) and not any(k in nick.lower() for k in CHANNEL_INDICATORS):
            cands.append(nick)
    seen, out = set(), []
    for c in cands:
        c = str(c).replace("@", "").strip()
        key = c.lower()
        if key in seen or not looks_like_person_name(c):
            continue
        seen.add(key)
        out.append(c)
    return " / ".join(out[:3])


def fetch_user_bio(unique_id):
    uid = (unique_id or "").lstrip("@").strip()
    if not uid:
        return ""
    try:
        r = http_get(f"{TIKWM}/user/search", {"keywords": uid, "count": 12})
        j = r.json()
    except Exception:
        return ""
    if not j or j.get("code") != 0:
        return ""
    for item in ((j.get("data") or {}).get("user_list") or []):
        u = item.get("user") or {}
        if (u.get("uniqueId") or "").lower() == uid.lower():
            return (u.get("signature") or "").strip()
    return ""


def classify(handle, title, tag, mentioned_users=""):
    h = (handle or "").lower()
    interviewish = is_interview_tag(tag) or any(k in (title or "").lower() for k in INTERVIEW_KEYWORDS)
    if interviewish and has_guest_on_camera(title, mentioned_users, tag):
        return "访谈/多人采访"
    if interviewish:
        return None
    if any(ind in h for ind in CHANNEL_INDICATORS):
        return "机构/频道账号"
    return "个人博主"


# ==========================================
# 💾 SQLite
# ==========================================

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video_hits (
            video_id TEXT PRIMARY KEY,
            handle TEXT,
            nickname TEXT,
            account_type TEXT,
            source_tag TEXT,
            duration INTEGER,
            play_count INTEGER,
            digg_count INTEGER,
            title TEXT,
            bio TEXT,
            on_screen_name TEXT,
            music_id TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hits_handle ON video_hits(handle)")
    for col, typ in (("bio", "TEXT"), ("on_screen_name", "TEXT"), ("music_id", "TEXT")):
        try:
            conn.execute(f"ALTER TABLE video_hits ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_bios (
            handle TEXT PRIMARY KEY,
            signature TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visited_music (
            music_id TEXT PRIMARY KEY
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visited_tags (
            tag TEXT PRIMARY KEY,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS challenge_ids (
            tag TEXT PRIMARY KEY,
            challenge_id TEXT
        )
    """)
    conn.commit()
    return conn


def get_db_progress(conn):
    df = qualified_accounts_df(conn)
    cur = conn.cursor()
    cur.execute("SELECT tag FROM visited_tags")
    visited = {row[0] for row in cur.fetchall()}
    return len(df), visited


def qualified_accounts_df(conn):
    df = pd.read_sql_query(
        """
        SELECT
            h.handle,
            h.nickname,
            h.account_type,
            h.source_tag,
            'https://www.tiktok.com/@' || REPLACE(h.handle, '@', '') AS url,
            h.n_videos,
            h.sample_duration,
            h.play_count,
            h.digg_count,
            h.sample_title,
            h.on_screen_name,
            h.bio
        FROM (
            SELECT
                handle,
                MAX(nickname) AS nickname,
                COALESCE(
                    MAX(CASE WHEN account_type LIKE '%访谈%' THEN account_type END),
                    MAX(account_type)
                ) AS account_type,
                GROUP_CONCAT(DISTINCT source_tag) AS source_tag,
                COUNT(*) AS n_videos,
                MAX(duration) AS sample_duration,
                MAX(play_count) AS play_count,
                MAX(digg_count) AS digg_count,
                MAX(title) AS sample_title,
                MAX(on_screen_name) AS on_screen_name,
                MAX(bio) AS bio
            FROM video_hits
            GROUP BY handle
            HAVING COUNT(*) >= ?
        ) h
        ORDER BY h.n_videos DESC, h.play_count DESC
        """,
        conn,
        params=(MIN_FACE_VIDEOS,),
    )
    return _filter_org_need_name(df)


def _filter_org_need_name(df):
    if df is None or df.empty:
        return df
    def keep(row):
        acc = str(row.get("account_type") or "")
        if "机构" not in acc:
            return True
        name = str(row.get("on_screen_name") or "").strip()
        return bool(name)
    return df[df.apply(keep, axis=1)].reset_index(drop=True)


def export_sharded_excels(conn):
    df = qualified_accounts_df(conn)
    if df.empty:
        print("💾 暂无账号可导出。")
        return
    df = df.rename(columns={
        "handle": "TikTok Handle",
        "nickname": "昵称",
        "account_type": "账号类型",
        "source_tag": "来源垂类标签",
        "url": "TikTok主页URL",
        "n_videos": "出镜作品条数(抽样)",
        "sample_duration": "抽样视频时长(秒)",
        "play_count": "抽样最高播放",
        "digg_count": "抽样最高点赞",
        "sample_title": "抽样视频文案",
        "on_screen_name": "出镜人名(标题/简介)",
        "bio": "账号简介",
    })
    total = len(df)
    num_chunks = (total + EXPORT_BATCH_SIZE - 1) // EXPORT_BATCH_SIZE
    for i in range(num_chunks):
        chunk = df.iloc[i * EXPORT_BATCH_SIZE: (i + 1) * EXPORT_BATCH_SIZE].copy()
        chunk.insert(0, "序号", range(i * EXPORT_BATCH_SIZE + 1, i * EXPORT_BATCH_SIZE + len(chunk) + 1))
        file_name = os.path.join(OUTPUT_DIR, f"TikTok_Clean_Accounts_Part_{i + 1:02d}.xlsx")
        chunk.to_excel(file_name, index=False)
    whole = df.copy()
    whole.insert(0, "序号", range(1, total + 1))
    whole.to_excel(os.path.join(OUTPUT_DIR, "TikTok_Clean_Accounts.xlsx"), index=False)
    print(f"💾 [导出完成] {total} 个去重账号 → {num_chunks} 个分表 + TikTok_Clean_Accounts.xlsx，目录 {OUTPUT_DIR}")


# ==========================================
# 🚀 接口扫描（不下封面）
# ==========================================

def resolve_challenge_id(tag):
    try:
        r = http_get(f"{TIKWM}/challenge/info", {"challenge_name": tag})
        j = r.json()
    except Exception:
        return None, False
    if getattr(r, "status_code", 0) == 403 or not j:
        return None, False
    if j.get("code") != 0:
        return None, True
    cid = str((j.get("data") or {}).get("id") or "")
    return (cid or None), True


def fetch_challenge_videos(challenge_id, pages):
    videos, cursor, ok = [], 0, False
    for _ in range(pages):
        try:
            r = http_get(
                f"{TIKWM}/challenge/posts",
                {"challenge_id": challenge_id, "count": min(30, VIDEOS_PER_TAG), "cursor": cursor},
            )
            j = r.json()
        except Exception:
            return videos, False
        if not j or j.get("code") != 0:
            return videos, ok
        ok = True
        data = j.get("data") or {}
        batch = data.get("videos") or []
        videos.extend(batch)
        if not data.get("hasMore") or not batch:
            break
        cursor = data.get("cursor") or (cursor + len(batch))
        time.sleep(random.uniform(0.15, 0.4))
    return videos, ok


def fetch_user_videos(unique_id, pages=2):
    videos, cursor = [], 0
    for _ in range(pages):
        try:
            r = http_get(
                f"{TIKWM}/user/posts",
                {"unique_id": unique_id, "count": 30, "cursor": cursor},
            )
            j = r.json()
        except Exception:
            break
        if not j or j.get("code") != 0:
            break
        data = j.get("data") or {}
        batch = data.get("videos") or []
        videos.extend(batch)
        if not data.get("hasMore") or not batch:
            break
        cursor = data.get("cursor") or (cursor + len(batch))
        time.sleep(random.uniform(0.15, 0.4))
    return videos


def fetch_music_videos(music_id, pages=1):
    """拍同款：同原声作品。失败则关闭后续尝试。"""
    global MUSIC_SNOWBALL_OK
    if not MUSIC_SNOWBALL_OK or not music_id:
        return []
    videos, cursor = [], 0
    for _ in range(pages):
        try:
            r = http_get(
                f"{TIKWM}/music/posts",
                {"music_id": music_id, "count": 20, "cursor": cursor},
            )
            if getattr(r, "status_code", 0) == 403 or "Just a moment" in (r.text[:80] if r.text else ""):
                MUSIC_SNOWBALL_OK = False
                print("⚠️ 拍同款/同原声接口被拦截（Cloudflare），已停用该通道")
                return []
            j = r.json()
        except Exception:
            MUSIC_SNOWBALL_OK = False
            return []
        if not j or j.get("code") != 0:
            MUSIC_SNOWBALL_OK = False
            return []
        data = j.get("data") or {}
        batch = data.get("videos") or []
        videos.extend(batch)
        if not data.get("hasMore") or not batch:
            break
        cursor = data.get("cursor") or (cursor + len(batch))
    return videos


_BIO_LOCK = threading.Lock()
_BIO_CACHE = {}


def cached_bio(unique_id):
    uid = (unique_id or "").lstrip("@")
    with _BIO_LOCK:
        if uid in _BIO_CACHE:
            return _BIO_CACHE[uid]
    sig = fetch_user_bio(uid)
    with _BIO_LOCK:
        _BIO_CACHE[uid] = sig
    return sig


def video_to_hit(v, tag, interview_tag):
    author = v.get("author") or {}
    handle = (author.get("unique_id") or "").lstrip("@").strip()
    if not handle or (handle.startswith("user") and handle[4:].isdigit()):
        return None
    title = v.get("title") or ""
    duration = int(v.get("duration") or 0)
    if interview_tag:
        if duration and not (MIN_DUR_INTERVIEW <= duration <= MAX_DUR_INTERVIEW):
            return None
    else:
        if duration and not (MIN_DUR_PERSONAL <= duration <= MAX_DUR_PERSONAL):
            return None
    if looks_spam(title, handle) or looks_overlay_heavy(title) or looks_faceless(title):
        return None
    mentioned = v.get("mentioned_users") or ""
    acc_type = classify(handle, title, tag, mentioned)
    if not acc_type:
        return None
    nick = author.get("nickname") or ""
    bio = ""
    name = extract_on_screen_name(title, bio, nick)
    if acc_type == "机构/频道账号":
        if not name:
            bio = cached_bio(handle)
            name = extract_on_screen_name(title, bio, nick)
        if not name:
            return None
    vid = str(v.get("video_id") or v.get("id") or "")
    if not vid:
        return None
    mid = str((v.get("music_info") or {}).get("id") or "")
    return (
        vid,
        f"@{handle}",
        nick,
        acc_type,
        f"#{tag}",
        duration or 0,
        int(v.get("play_count") or 0),
        int(v.get("digg_count") or 0),
        title[:180],
        (bio or "")[:180],
        name,
        mid,
    )


def scan_single_tag(tag):
    time.sleep(random.uniform(0.08, 0.3))
    hits, new_tags = [], set()
    cid, info_ok = resolve_challenge_id(tag)
    if not cid:
        return tag, hits, new_tags, None, info_ok, 0

    interview_tag = is_interview_tag(tag)
    videos, posts_ok = fetch_challenge_videos(cid, PAGES_PER_TAG)
    if not posts_ok:
        return tag, hits, new_tags, cid, False, 0

    music_ids = []
    for v in videos:
        mid = str((v.get("music_info") or {}).get("id") or "")
        if mid and mid not in music_ids:
            music_ids.append(mid)
        hit = video_to_hit(v, tag, interview_tag)
        if not hit:
            continue
        hits.append(hit)
        for ct in re.findall(r"#([A-Za-z0-9_\u4e00-\u9fff]+)", hit[8]):
            if is_safe_snowball_tag(ct):
                new_tags.add(ct.lower())

    extra_music = 0
    if MUSIC_SNOWBALL_OK:
        seen_vid = {h[0] for h in hits}
        for mid in music_ids[:2]:
            more = fetch_music_videos(mid, pages=1)
            extra_music += len(more)
            for v in more:
                hit = video_to_hit(v, tag + "_sound", interview_tag)
                if not hit or hit[0] in seen_vid:
                    continue
                seen_vid.add(hit[0])
                hits.append(hit)
            if not MUSIC_SNOWBALL_OK:
                break
    return tag, hits, new_tags, cid, True, extra_music


def ordered_seed_tags(visited):
    seeds = generate_initial_tags()
    random.shuffle(seeds)
    pri = [t for t in PRIORITY_TAGS if t not in visited]
    rest = [t for t in seeds if t not in visited and t not in pri]
    return pri + rest


def backfill_names(conn):
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT video_id, handle, nickname, title, IFNULL(bio,''), IFNULL(on_screen_name,''), account_type "
        "FROM video_hits"
    ).fetchall()
    bios = {}
    n = 0
    for vid, handle, nick, title, bio, old, acc in rows:
        name = old or extract_on_screen_name(title or "", bio or "", nick or "")
        if "机构" in (acc or "") and not name:
            if handle not in bios:
                bios[handle] = cached_bio(handle)
            bio2 = bios[handle]
            name = extract_on_screen_name(title or "", bio2, nick or "")
            if bio2 and bio2 != bio:
                cur.execute("UPDATE video_hits SET bio=? WHERE video_id=?", (bio2[:180], vid))
        if name and name != old:
            cur.execute("UPDATE video_hits SET on_screen_name=? WHERE video_id=?", (name, vid))
            n += 1
    conn.commit()
    print(f"📝 已回填出镜人名 {n} 条")


def main():
    conn = init_db()
    backfill_names(conn)
    total_collected, visited_tags = get_db_progress(conn)
    tag_queue = deque(ordered_seed_tags(visited_tags))
    queued_set = set(tag_queue) | visited_tags

    print(f"📊 已达标账号(≥{MIN_FACE_VIDEOS}条出镜作品): {total_collected} / {TARGET_TOTAL_ACCOUNTS}")
    print(f"🌱 待爬标签: {len(tag_queue)}（已跳过 {len(visited_tags)}）")
    print("🚫 不调用浏览器、不下载封面，只读接口元数据")

    last_export_milestone = (total_collected // EXPORT_BATCH_SIZE) * EXPORT_BATCH_SIZE

    try:
        while tag_queue and total_collected < TARGET_TOTAL_ACCOUNTS:
            batch_tags = []
            while tag_queue and len(batch_tags) < FETCH_WORKERS:
                batch_tags.append(tag_queue.popleft())

            with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
                futures = {executor.submit(scan_single_tag, t): t for t in batch_tags}
                for future in as_completed(futures):
                    try:
                        unpacked = future.result()
                        if len(unpacked) == 5:
                            tag, hits, snowballed_tags, cid, ok = unpacked
                            extra_music = 0
                        else:
                            tag, hits, snowballed_tags, cid, ok, extra_music = unpacked
                    except Exception as e:
                        print(f"[worker] 任务异常 {type(e).__name__}: {e}")
                        continue
                    cur = conn.cursor()
                    if ok:
                        cur.execute("INSERT OR IGNORE INTO visited_tags (tag) VALUES (?)", (tag,))
                    else:
                        tag_queue.append(tag)
                        print(f"[#{tag:<22}] 接口失败，稍后重试")
                    if cid:
                        cur.execute(
                            "INSERT OR REPLACE INTO challenge_ids (tag, challenge_id) VALUES (?, ?)",
                            (tag, cid),
                        )
                    if hits:
                        cur.executemany(
                            "INSERT OR IGNORE INTO video_hits "
                            "(video_id, handle, nickname, account_type, source_tag, duration, "
                            "play_count, digg_count, title, bio, on_screen_name, music_id) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            hits,
                        )
                    conn.commit()

                    added_tags = 0
                    for st in snowballed_tags:
                        if st not in queued_set:
                            queued_set.add(st)
                            tag_queue.append(st)
                            added_tags += 1

                    total_collected, _ = get_db_progress(conn)
                    print(
                        f"[#{tag:<22}] 本页作品: {len(hits):>3} | "
                        f"同款+{extra_music:<2} | 新Tag +{added_tags:<2} | 队列 {len(tag_queue):>4} | "
                        f"达标账号 {total_collected:>5}/{TARGET_TOTAL_ACCOUNTS}"
                    )

                    if total_collected - last_export_milestone >= EXPORT_BATCH_SIZE:
                        last_export_milestone = (total_collected // EXPORT_BATCH_SIZE) * EXPORT_BATCH_SIZE
                        export_sharded_excels(conn)
                    if total_collected >= TARGET_TOTAL_ACCOUNTS:
                        break

    except KeyboardInterrupt:
        print("\n⚠️ 已中断，进度在 SQLite，下次会续跑。")
    finally:
        export_sharded_excels(conn)
        conn.close()
        print("🎉 任务结束。")


if __name__ == "__main__":
    main()
