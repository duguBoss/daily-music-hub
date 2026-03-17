import os
import json
import time
import shutil
import random
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO

# ================= 配置区 =================
TOP_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"

GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "your_username/your_repo")
BRANCH = "main"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ================= 1. 每周清空机制 =================
def clean_weekly():
    if datetime.now().weekday() == 0:
        if os.path.exists("outputs"):
            shutil.rmtree("outputs")
            print("今天是周一，已清空历史数据。")
    os.makedirs("outputs/images", exist_ok=True)

# ================= 2. 获取 Deezer 音乐数据 (免授权/超稳定/无防盗链) =================
def get_music_data():
    try:
        # 获取榜单前 50 首，每日随机挑一首，保持新鲜感
        res = requests.get("https://api.deezer.com/chart/0/tracks?limit=50", timeout=10).json()
        if "data" in res and len(res["data"]) > 0:
            track = random.choice(res["data"])
            return {
                "name": track["title"],
                "artist": track["artist"]["name"],
                "picUrl": track["album"]["cover_xl"]  # 直接拿 1000x1000 超清大图！
            }
    except Exception as e:
        print(f"Deezer API 请求失败: {e}")
        
    # 保底国际热歌数据
    print("使用保底音乐数据...")
    return {
        "name": "Shape of You",
        "artist": "Ed Sheeran",
        # Deezer 官方永久直链图
        "picUrl": "https://e-cdns-images.dzcdn.net/images/cover/f420e6e73715c0d291afb434407b4618/1000x1000-000000-80-0-0.jpg"
    }

# ================= 3. 调用 Gemini 生成文案 =================
def generate_content_with_gemini(song, artist):
    if not GEMINI_API_KEY:
        print("未检测到 GEMINI_API_KEY，使用备用文案。")
        return f"今日分享 | 治愈神曲《{song}》", f"有些歌，听的是旋律；有些歌，听的是自己。这首来自 {artist} 的《{song}》，你听懂了吗？"

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json"
    }
    
    prompt = f"""
    请为微信公众号写一段关于欧美/国际流行歌曲《{song}》（歌手：{artist}）的分享文案。
    要求：
    1. 包含一个吸引人的公众号文章标题（带有高级感或治愈感）。
    2. 包含一段约80字左右的正文，描述这首歌的听感（比如节奏感、慵懒、治愈或emo）。
    3. 严格按以下JSON格式返回，不要带有任何Markdown代码块(```json)标记：
    {{"title": "你的标题", "content": "你的正文"}}
    """

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        
        text = text.strip().strip("`").removeprefix("json").strip()
        data = json.loads(text)
        return data.get("title", f"今日欧美推歌 | 《{song}》"), data.get("content", "耳机一戴，进入属于你自己的世界。")
    except Exception as e:
        print(f"Gemini API 调用失败: {e}")
        return f"今日推歌 | 《{song}》", f"按下播放键，感受 {artist} 带来的极致听觉享受。"

# ================= 4. 生成封面图片 (适配 1000x1000 高清图) =================
def generate_cover(music):
    width, height = 900, 1200
    date_str = datetime.now().strftime("%Y-%m-%d")
    img_filename = f"{date_str}.jpg"
    img_path = f"outputs/images/{img_filename}"

    try:
        # Deezer 没有防盗链，直接下！
        response = requests.get(music['picUrl'], timeout=15)
        response.raise_for_status() 
        cover_img = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as e:
        print(f"❌ 图片下载失败! 原因: {e}")
        cover_img = Image.new("RGB", (1000, 1000), (44, 62, 80))

    # 背景模糊处理 (使用高清图模糊，质感更好)
    bg_img = cover_img.resize((width, width))
    bg_img = bg_img.resize((width, height), Image.Resampling.LANCZOS)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=35))
    
    # 封面主图居中 (保留 600x600 的大小)
    cover_size = 600
    cover_img_resized = cover_img.resize((cover_size, cover_size), Image.Resampling.LANCZOS)
    
    final_img = Image.new("RGB", (width, height))
    final_img.paste(bg_img, (0, 0))
    
    # 遮罩层让文字清晰
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 120))
    final_img.paste(mask, (0, 0), mask)
    final_img.paste(cover_img_resized, ((width - cover_size) // 2, 180))

    draw = ImageDraw.Draw(final_img)
    try:
        font_title = ImageFont.truetype("font.ttf", 60)
        font_artist = ImageFont.truetype("font.ttf", 40)
        font_date = ImageFont.truetype("font.ttf", 35)
    except:
        font_title = font_artist = font_date = ImageFont.load_default()

    def draw_text_center(y, text, font, color):
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), text, font=font, fill=color)

    # 欧美歌曲名可能较长，做个简单截断防溢出
    display_name = music['name'] if len(music['name']) < 18 else music['name'][:16] + "..."
    
    draw_text_center(840, f"{display_name}", font_title, (255, 255, 255))
    draw_text_center(930, f"- {music['artist']} -", font_artist, (200, 200, 200))
    draw_text_center(1080, f"🎵 {date_str} Daily Pick", font_date, (255, 255, 255))

    final_img.save(img_path, quality=95)
    return f"https://raw.githubusercontent.com/{GITHUB_REPO}/{BRANCH}/outputs/images/{img_filename}"

# ================= 5. 生成微信 HTML =================
def generate_wechat_html(music, img_url, content):
    html_content = f"""
    <section style="box-sizing: border-box; max-width: 100%; letter-spacing: 1px; font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; background-color: #ffffff; padding: 10px;">
        <p style="text-align: center; margin-bottom: 20px;">
            <img src="{TOP_GIF}" style="width: 100%; max-width: 600px; display: inline-block;" />
        </p>
        <section style="margin: 20px 0; text-align: center;">
            <h2 style="font-size: 22px; color: #333333; margin: 0; padding-bottom: 10px; border-bottom: 2px solid #e0e0e0; display: inline-block;">
                今日份宝藏音乐掉落 🎧
            </h2>
        </section>
        <section style="background-color: #f7f9fa; border-radius: 12px; padding: 20px; margin: 20px 0; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
            <p style="margin: 5px 0; font-size: 17px; color: #2c3e50;"><strong>🎵 Track：</strong>{music['name']}</p>
            <p style="margin: 5px 0; font-size: 16px; color: #7f8c8d;"><strong>🎤 Artist：</strong>{music['artist']}</p>
        </section>
        <p style="text-align: center; margin: 25px 0;">
            <img src="{img_url}" style="width: 100%; max-width: 500px; border-radius: 16px; box-shadow: 0 8px 20px rgba(0,0,0,0.15);" />
        </p>
        <section style="margin: 30px 0;">
            <p style="font-size: 16px; color: #555555; line-height: 1.8; text-indent: 2em; margin-bottom: 15px;">
                {content}
            </p>
            <p style="font-size: 16px; color: #555555; line-height: 1.8; text-indent: 2em;">
                喜欢的家人们记得长按保存上方的高清分享壁纸，发朋友圈或者设为屏保都超有质感！别忘了在评论区分享你今天的心情哦~
            </p>
        </section>
        <p style="text-align: center; margin-top: 40px;">
            <img src="{BOTTOM_GIF}" style="width: 100%; max-width: 600px; display: inline-block;" />
        </p>
    </section>
    """
    return html_content

# ================= 6. 保存 JSON =================
def save_json(title, img_url, html):
    json_path = "outputs/daily_post.json"
    data_list = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data_list = json.load(f)
        except:
            pass

    new_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "title": title,
        "covers": [img_url],
        "html": html.strip()
    }
    data_list.insert(0, new_data)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    clean_weekly()
    
    music = get_music_data()
    print(f"🎵 成功获取歌曲: {music['name']} - {music['artist']}")
    
    print("🤖 正在呼叫 Gemini 生成文案...")
    ai_title, ai_content = generate_content_with_gemini(music['name'], music['artist'])
    print(f"✨ 标题: {ai_title}")
    
    img_url = generate_cover(music)
    print(f"🖼️ 图片已生成: {img_url}")
    
    html_str = generate_wechat_html(music, img_url, ai_content)
    save_json(ai_title, img_url, html_str)
    print("✅ JSON 与 HTML 更新完成！")
