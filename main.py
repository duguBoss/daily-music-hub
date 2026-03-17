import os
import json
import shutil
import random
import requests
import urllib3
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO

# 忽略 SSL 证书报错
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置
TOP_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "your_username/your_repo")
BRANCH = "main"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HISTORY_FILE = "history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history[-300:], f, ensure_ascii=False, indent=4)

def get_unique_music(count=2):
    history = load_history()
    selected = []
    try:
        res = requests.get("https://api.deezer.com/chart/0/tracks?limit=50", timeout=10).json()
        all_tracks = res.get("data", [])
        for track in all_tracks:
            if track["title"] not in history:
                selected.append({
                    "name": track["title"],
                    "artist": track["artist"]["name"],
                    "picUrl": track["album"]["cover_xl"]
                })
                history.append(track["title"])
                if len(selected) == count: break
    except:
        pass
    save_history(history)
    return selected

def generate_content_with_gemini(song, artist):
    if not GEMINI_API_KEY:
        return f"今日推歌：{song}", "这首歌的旋律非常动人，值得你细细品味。"
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    prompt = f"为微信公众号写一段关于歌曲《{song}》（歌手：{artist}）的走心文案，要求：1.标题要有高级感，2.正文约100字，3.直接返回JSON格式：{{\"title\": \"...\", \"content\": \"...\"}}，不要Markdown。"
    try:
        response = requests.post(url, headers=headers, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=20)
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"].replace("```json", "").replace("```", "")
        data = json.loads(text)
        return data.get("title", f"今日推歌：{song}"), data.get("content", "感受旋律的力量。")
    except:
        return f"今日推歌：{song}", "音乐是灵魂的避风港。"

def generate_cover(music, index):
    width, height = 900, 1200
    date_str = datetime.now().strftime("%Y-%m-%d")
    img_path = f"outputs/images/{date_str}_{index}.jpg"
    try:
        res = requests.get(music['picUrl'], timeout=10)
        cover_img = Image.open(BytesIO(res.content)).convert("RGB")
    except:
        cover_img = Image.new("RGB", (1000, 1000), (44, 62, 80))

    bg = cover_img.resize((width, height)).filter(ImageFilter.GaussianBlur(30))
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 120))
    bg.paste(mask, (0, 0), mask)
    cover_small = cover_img.resize((600, 600))
    bg.paste(cover_small, ((width-600)//2, 200))
    
    draw = ImageDraw.Draw(bg)
    font = ImageFont.truetype("font.ttf", 50) if os.path.exists("font.ttf") else ImageFont.load_default()
    draw.text((width//2, 850), music['name'], font=font, fill="white", anchor="mm")
    bg.save(img_path, quality=90)
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{BRANCH}/{img_path}"

def main():
    if datetime.now().weekday() == 0 and os.path.exists("outputs"): shutil.rmtree("outputs")
    os.makedirs("outputs/images", exist_ok=True)
    
    songs = get_unique_music(2)
    covers = []
    html_body = f"<p style='text-align:center;'><img src='{TOP_GIF}' style='width:100%'></p>"
    
    for i, s in enumerate(songs):
        title, content = generate_content_with_gemini(s['name'], s['artist'])
        img_url = generate_cover(s, i)
        covers.append(img_url)
        html_body += f"""
        <section style='margin:20px 0; padding:15px; border-bottom:1px solid #eee;'>
            <h2 style='color:#333; font-size:20px;'>{s['name']} - {s['artist']}</h2>
            <img src='{img_url}' style='width:100%; border-radius:12px; margin:10px 0;'>
            <p style='color:#555; line-height:1.8; font-size:16px;'>{content}</p>
        </section>
        """
    
    html_body += f"<p style='text-align:center;'><img src='{BOTTOM_GIF}' style='width:100%'></p>"
    
    final_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": f"今日音乐清单：{songs[0]['name']} & {songs[1]['name']}",
        "covers": covers,
        "weixin_html": html_body
    }
    
    with open("outputs/daily_post.json", "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
