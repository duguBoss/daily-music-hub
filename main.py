import json
import os
import random
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ================= Configuration =================
TOP_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"
WECHAT_SIDE_SPACING_PX = 0
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "duguBoss/daily-music-hub")
BRANCH = "main"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HISTORY_FILE = "history.json"
OUTPUT_FILE = "outputs/daily_post.json"
BEIJING_TZ = timezone(timedelta(hours=8))

GEMINI_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_MODELS",
        "gemini-3-flash-preview,gemini-2.5-flash,gemini-2.0-flash",
    ).split(",")
    if model.strip()
]
GEMINI_MODEL_RETRIES = max(1, int(os.getenv("GEMINI_MODEL_RETRIES", "2")))


def ensure_top_guide_gif(html):
    normalized = (html or "").strip()
    if TOP_GIF in normalized:
        return normalized
    return f"<img src='{TOP_GIF}' style='width:100%;display:block;margin-bottom:1em;'>" + normalized


def normalize_text(value):
    cleaned = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def safe_text(value):
    return str(value or "").replace("<", "＜").replace(">", "＞").strip()


def shorten_text(text, max_len):
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return []

    if isinstance(data, list):
        return [str(item) for item in data if str(item).strip()]

    if isinstance(data, dict):
        tracks = data.get("tracks", [])
        return [str(item) for item in tracks if str(item).strip()]

    return []


def save_history(history_keys):
    unique_keys = list(dict.fromkeys(history_keys))
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(unique_keys[-500:], file, ensure_ascii=False, indent=2)


def track_to_item(track):
    title = safe_text(track.get("title"))
    artist = safe_text((track.get("artist") or {}).get("name"))
    album = track.get("album") or {}
    pic = (
        album.get("cover_xl")
        or album.get("cover_big")
        or album.get("cover_medium")
        or album.get("cover")
    )
    if not title or not artist or not pic:
        return None

    key = normalize_text(f"{title} {artist}")
    if not key:
        return None

    return {
        "name": title,
        "artist": artist,
        "picUrl": pic,
        "track_key": key,
    }


def get_unique_music(count=2):
    history_keys = load_history()
    history_set = set(history_keys)
    selected = []

    try:
        response = requests.get("https://api.deezer.com/chart/0/tracks?limit=100", timeout=12)
        response.raise_for_status()
        all_tracks = response.json().get("data", [])
    except Exception:
        all_tracks = []

    random.shuffle(all_tracks)

    for track in all_tracks:
        item = track_to_item(track)
        if not item:
            continue
        if item["track_key"] in history_set:
            continue
        if any(song["track_key"] == item["track_key"] for song in selected):
            continue
        selected.append(item)
        history_keys.append(item["track_key"])
        history_set.add(item["track_key"])
        if len(selected) >= count:
            break

    # Fallback: if history is too strict, allow songs not selected today.
    if len(selected) < count:
        for track in all_tracks:
            item = track_to_item(track)
            if not item:
                continue
            if any(song["track_key"] == item["track_key"] for song in selected):
                continue
            selected.append(item)
            if len(selected) >= count:
                break

    save_history(history_keys)
    return [{k: v for k, v in song.items() if k != "track_key"} for song in selected]


def parse_model_json(text):
    cleaned = re.sub(r"```json\s*|```", "", (text or "")).strip()
    if not cleaned:
        raise ValueError("Model returned empty text.")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"Model output is not valid JSON. Preview: {cleaned[:300]}")
        return json.loads(cleaned[start : end + 1])


def extract_gemini_text(payload):
    if not isinstance(payload, dict):
        raise ValueError("Gemini payload is not a JSON object.")

    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        raise RuntimeError(
            f"Gemini API error ({error.get('code', 'unknown')}/{error.get('status', 'UNKNOWN')}): "
            f"{error.get('message', 'unknown error')}"
        )

    candidates = payload.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text

    finish_reasons = [candidate.get("finishReason") for candidate in candidates if isinstance(candidate, dict)]
    raise RuntimeError(
        f"Gemini returned no usable candidates. finishReasons={finish_reasons}, "
        f"promptFeedback={payload.get('promptFeedback')}"
    )


def request_gemini(prompt, model_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    response = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=45,
    )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw_text": response.text[:500]}

    if response.status_code >= 400:
        message = payload.get("error", {}).get("message", str(payload))
        raise RuntimeError(f"Gemini HTTP {response.status_code} with model {model_name}: {message}")

    return payload


def build_fallback_copy(songs):
    title_seed = " / ".join(shorten_text(song["name"], 8) for song in songs[:2])
    post_title = shorten_text(f"今日循环歌单：{title_seed}", 16)
    opening = (
        "如果你今天状态有点乱，这份歌单可以帮你把节奏拉回来。"
        "我挑了两首情绪层次很清晰的歌：一首稳住当下，一首点燃行动。"
    )
    songs_copy = []
    for idx, song in enumerate(songs, 1):
        songs_copy.append(
            {
                "hook": f"{idx}. {shorten_text(song['name'], 18)}",
                "analysis": (
                    f"《{song['name']}》的旋律推进很干净，{song['artist']}把情绪控制在一个刚好可共鸣的范围。"
                    "你不会被过度煽情拖走，而是能在几分钟内快速进入专注状态。"
                ),
                "scene": "通勤路上、午后低能量时段、晚上收工后",
                "one_liner": "先把这首加进收藏，情绪低点时直接单曲循环。",
            }
        )

    return {
        "post_title": post_title,
        "opening": opening,
        "songs": songs_copy,
        "ending_question": "你今天最想单曲循环哪一首？留言告诉我，我会把高赞评论做成下期歌单。",
    }


def generate_post_copy(songs):
    fallback = build_fallback_copy(songs)
    if not GEMINI_API_KEY:
        return fallback

    song_info = [{"name": song["name"], "artist": song["artist"]} for song in songs]
    prompt = f"""
You are a senior WeChat music-content editor.
Generate recommendation copy optimized for WeChat distribution quality signals.

Output language:
1) Simplified Chinese only.
2) Keep the style concise, useful, and emotionally resonant.
3) Avoid clickbait words such as: 震惊, 必看, 绝了, 史上最.

Return strictly in JSON:
{{
  "post_title": "string",
  "opening": "string",
  "songs": [
    {{
      "hook": "string",
      "analysis": "string",
      "scene": "string",
      "one_liner": "string"
    }}
  ],
  "ending_question": "string"
}}

Rules:
1) post_title: <= 16 Chinese characters, include clear user benefit.
2) opening: 120-180 Chinese characters, pain point + expected gain.
3) songs length must be exactly {len(song_info)} and keep the same order as input.
4) Each song.analysis: 90-140 Chinese characters, no fake facts, no extreme claims.
5) scene: one short line with 2-3 usage scenarios.
6) one_liner: <= 32 Chinese characters, suitable for highlighted quote.
7) ending_question: one concrete interaction question that encourages save/like/share naturally.

Input songs:
{json.dumps(song_info, ensure_ascii=False)}
"""

    last_error = None
    for model_name in GEMINI_MODELS:
        for attempt in range(1, GEMINI_MODEL_RETRIES + 1):
            try:
                payload = request_gemini(prompt, model_name)
                text = extract_gemini_text(payload)
                data = parse_model_json(text)

                songs_copy = data.get("songs")
                if not isinstance(songs_copy, list) or len(songs_copy) != len(song_info):
                    raise ValueError("Model returned invalid songs array length.")

                return {
                    "post_title": safe_text(data.get("post_title")) or fallback["post_title"],
                    "opening": safe_text(data.get("opening")) or fallback["opening"],
                    "songs": [
                        {
                            "hook": safe_text(item.get("hook")) or fallback["songs"][idx]["hook"],
                            "analysis": safe_text(item.get("analysis")) or fallback["songs"][idx]["analysis"],
                            "scene": safe_text(item.get("scene")) or fallback["songs"][idx]["scene"],
                            "one_liner": safe_text(item.get("one_liner")) or fallback["songs"][idx]["one_liner"],
                        }
                        for idx, item in enumerate(songs_copy)
                    ],
                    "ending_question": safe_text(data.get("ending_question")) or fallback["ending_question"],
                }
            except Exception as exc:
                last_error = exc
                if attempt < GEMINI_MODEL_RETRIES:
                    time.sleep(1.5 * attempt)

    print(f"[WARN] Gemini copy generation failed. Fallback is used. Last error: {last_error}")
    return fallback


def generate_cover(song, index):
    width, height = 900, 1200
    date_str = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    img_path = f"outputs/images/{date_str}_{index}.jpg"

    try:
        res = requests.get(song["picUrl"], timeout=12)
        res.raise_for_status()
        cover_img = Image.open(BytesIO(res.content)).convert("RGB")
    except Exception:
        cover_img = Image.new("RGB", (1000, 1000), (44, 62, 80))

    background = cover_img.resize((width, height)).filter(ImageFilter.GaussianBlur(30))
    dark_mask = Image.new("RGBA", (width, height), (0, 0, 0, 130))
    background.paste(dark_mask, (0, 0), dark_mask)

    cover_small = cover_img.resize((560, 560))
    background.paste(cover_small, ((width - 560) // 2, 180))

    draw = ImageDraw.Draw(background)
    title_font = ImageFont.truetype("font.ttf", 54) if os.path.exists("font.ttf") else ImageFont.load_default()
    artist_font = ImageFont.truetype("font.ttf", 34) if os.path.exists("font.ttf") else ImageFont.load_default()

    draw.text(
        (width // 2, 820),
        shorten_text(song["name"], 26),
        font=title_font,
        fill="white",
        anchor="mm",
    )
    draw.text(
        (width // 2, 890),
        shorten_text(song["artist"], 28),
        font=artist_font,
        fill=(230, 230, 230),
        anchor="mm",
    )

    background.save(img_path, quality=90)
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{BRANCH}/{img_path}"


def render_wechat_html(post_copy, songs, covers):
    title = safe_text(post_copy.get("post_title"))
    opening = safe_text(post_copy.get("opening"))
    ending_question = safe_text(post_copy.get("ending_question"))
    song_copies = post_copy.get("songs", [])

    html_parts = [
        (
            f"<section data-side-spacing='{WECHAT_SIDE_SPACING_PX}' "
            "style='background-color:#f6f7f9;margin:0;padding:0;'>"
        ),
        f"<img src='{TOP_GIF}' style='width:100%;display:block;'>",
        (
            f"<section style='padding:28px {WECHAT_SIDE_SPACING_PX}px 8px {WECHAT_SIDE_SPACING_PX}px;background-color:#ffffff;"
            "font-family:-apple-system,BlinkMacSystemFont,Helvetica Neue,PingFang SC,Hiragino Sans GB,Microsoft YaHei,sans-serif;'>"
        ),
        (
            "<section style='border-radius:14px;background:linear-gradient(135deg,#f8fbff 0%,#f2f8ff 100%);"
            "padding:18px 16px;margin-bottom:24px;'>"
            f"<h1 style='margin:0;color:#1f2d3d;font-size:24px;line-height:1.4;'>{title}</h1>"
            f"<p style='margin:12px 0 0 0;color:#3c4a59;line-height:1.95;font-size:15px;'>{opening}</p>"
            "</section>"
        ),
    ]

    for idx, song in enumerate(songs):
        copy = song_copies[idx] if idx < len(song_copies) else {}
        hook = safe_text(copy.get("hook") or song["name"])
        analysis = safe_text(copy.get("analysis"))
        scene = safe_text(copy.get("scene"))
        one_liner = safe_text(copy.get("one_liner"))
        song_name = safe_text(song["name"])
        artist = safe_text(song["artist"])
        img_url = covers[idx] if idx < len(covers) else ""

        html_parts.append(
            "<section style='margin:0 0 22px 0;padding:16px;border:1px solid #edf1f4;"
            "border-radius:14px;background:#ffffff;box-shadow:0 6px 16px rgba(0,0,0,0.03);'>"
        )
        html_parts.append(
            f"<h3 style='margin:0 0 8px 0;font-size:19px;color:#1f2d3d;line-height:1.45;'>No.{idx + 1} {hook}</h3>"
        )
        html_parts.append(
            f"<p style='margin:0 0 12px 0;font-size:14px;color:#5f6c7b;line-height:1.7;'>{song_name} · {artist}</p>"
        )
        html_parts.append(
            f"<img src='{img_url}' style='width:100%;display:block;border-radius:12px;margin:0 0 14px 0;'>"
        )
        html_parts.append(
            f"<p style='margin:0 0 10px 0;font-size:15px;color:#2d3a48;line-height:1.95;'><strong>推荐理由：</strong>{analysis}</p>"
        )
        html_parts.append(
            f"<p style='margin:0 0 10px 0;font-size:15px;color:#2d3a48;line-height:1.95;'><strong>适合场景：</strong>{scene}</p>"
        )
        html_parts.append(
            "<blockquote style='margin:0;background:#f6fbff;border-left:3px solid #07c160;"
            f"padding:10px 12px;color:#40566d;font-size:14px;line-height:1.8;'>{one_liner}</blockquote>"
        )
        html_parts.append("</section>")

    html_parts.append(
        "<section style='margin:4px 0 20px 0;padding:16px;border-radius:12px;background:#fffaf0;border:1px solid #ffe5b3;'>"
        f"<p style='margin:0;font-size:15px;color:#5e4b2f;line-height:1.9;'><strong>互动话题：</strong>{ending_question}</p>"
        "<p style='margin:10px 0 0 0;font-size:14px;color:#7a6442;line-height:1.9;'>"
        "如果这份歌单对你有帮助，欢迎点个在看、收藏，或转发给同样需要音乐续命的朋友。</p>"
        "</section>"
    )
    html_parts.append("</section>")
    html_parts.append(f"<img src='{BOTTOM_GIF}' style='width:100%;display:block;'>")
    html_parts.append("</section>")
    return ensure_top_guide_gif("".join(html_parts))


def build_default_title(songs):
    names = [shorten_text(song["name"], 8) for song in songs[:2]]
    if not names:
        return "今日音乐推荐"
    if len(names) == 1:
        return shorten_text(f"今日推荐：{names[0]}", 16)
    return shorten_text(f"今日循环：{names[0]} | {names[1]}", 16)


def main():
    now_dt = datetime.now(BEIJING_TZ)
    if now_dt.weekday() == 0 and os.path.exists("outputs"):
        shutil.rmtree("outputs")
    os.makedirs("outputs/images", exist_ok=True)

    songs = get_unique_music(count=2)
    if not songs:
        raise RuntimeError("No songs fetched from Deezer chart API.")

    post_copy = generate_post_copy(songs)
    covers = [generate_cover(song, idx) for idx, song in enumerate(songs)]
    weixin_html = render_wechat_html(post_copy, songs, covers)

    final_data = {
        "date": now_dt.strftime("%Y-%m-%d"),
        "title": safe_text(post_copy.get("post_title")) or build_default_title(songs),
        "covers": covers,
        "songs": [{"name": song["name"], "artist": song["artist"]} for song in songs],
        "weixin_html": weixin_html,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(final_data, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
