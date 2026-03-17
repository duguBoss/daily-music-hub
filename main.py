import os
import json
import time
import shutil
import random
import requests
import urllib3
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO

# 忽略 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= 配置区 =================
TOP_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzXgUR7FJnf11qGIo8nmKt6RxibXrb5s4RFb9UZ9UOHQy7fqQyI377Licw/0?wx_fmt=gif"
BOTTOM_GIF = "https://mmbiz.qpic.cn/mmbiz_gif/3hAJnwuyZuicicZkgJBUCCaricdibomDBrTzk57DCmhVC16o9ILH0Tn1YPEiarfLRRQSVFN2mJdeYibGnBPialPIzvojw/0?wx_fmt=gif"

GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "your_username/your_repo")
BRANCH = "main"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") # 从环境变量读取 Gemini Key

# 请求头，防止网易云/其他图床拦截
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ================= 1. 每周清空机制 =================
def clean_weekly():
    if datetime.now().weekday() == 0:
        if os.path.exists("outputs"):
            shutil.rmtree("outputs")
            print("今天是周一，已清空历史数据。")
    os.makedirs("outputs/images", exist_ok=True)

# ================= 2. 获取音乐数据 =================
def get_music_data():
    try:
        # 添加 verify=False 解决证书过期问题
        res = requests.get("https://api.uomg.com/api/rand.music?sort=热歌榜&format=json", headers=HEADERS, verify=False, timeout=10).json()
        if res.get("code") == 1:
            data = res["data"]
            return {
                "name": data["name"],
                "artist": data["artistsname"],
                "picUrl": data["picurl"],
            }
    except Exception as e:
        print(f"音乐API请求失败: {e}")
        
    # 如果全失败，使用保底数据 (修复了更稳定的图片链接)
    return {
        "name": "海底",
        "artist": "一支榴莲",
        "picUrl": "https://p2.music.126.net/rINn3QJkH7nK_1r3K2k9VQ==/109951164803767222.jpg?param=800y800"
    }

# ================= 3. 调用 Gemini 生成文案 =================
def generate_content_with_gemini(song, artist):
    if not GEMINI_API_KEY:
        print("未检测到 GEMINI_API_KEY，使用备用文案。")
        return f"今日分享 | 治愈神曲《{song}》", f"有些歌，听的是旋律；有些歌，听的是自己。这首《{song}》里的故事，你听懂了吗？"

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent"
    headers = {
        "x-goog-api-key": GEMINI_API_KEY,
        "Content-Type": "application/json"
    }
    
    # 精心设计的 Prompt，要求 Gemini 返回 JSON 格式
    prompt = f"""
    请为微信公众号写一段关于歌曲《{song}》（歌手：{artist}）的分享文案。
    要求：
    1. 包含一个吸引人的公众号文章标题（带有情绪价值或治愈感）。
    2. 包含一段约80字左右的走心、治愈或emo的听后感正文。
    3. 严格按以下JSON格式返回，不要带有任何Markdown代码块(```json)标记：
    {{"title": "你的标题", "content": "你的正文"}}
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        result = response.json()
        text = result["candidates"][0]["content"]["parts"][0]["text"]
        
        # 清理可能存在的 markdown 标记
        text = text.strip().strip("`").removeprefix("json").strip()
        data = json.loads(text)
        
        return data.get("title", f"今日分享 | 《{song}》"), data.get("content", "耳机一戴，谁也不爱。")
    except Exception as e:
        print(f"Gemini API 调用失败: {e}")
        return f"今日推歌 | 《{song}》", "这首歌的前奏一响，瞬间就被拉回了那个特别的时刻。"

# ================= 4. 生成封面图片 =================
def generate_cover(music):
    width, height = 900, 1200
    date_str = datetime.now().strftime("%Y-%m-%d")
    img_filename = f"{date_str}.jpg"
    img_path = f"outputs/images/{img_filename}"

    # 下载图片 (添加 Headers 防止 403 拦截)
    try:
        response = requests.get(music['picUrl'], headers=HEADERS, timeout=10)
        response.raise_for_status() # 如果是 403, 404 等会直接报错跳入 except
        cover_img = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as e:
        print(f"图片下载失败 ({e})，使用纯色背景替代")
        # 如果依然下载失败，生成一张灰色背景保底，防止程序崩溃
        cover_img = Image.new("RGB", (600, 600), (44, 62, 80))

    bg_img = cover_img.resize((width, width))
    bg_img = bg_img.resize((width, height), Image.Resampling.LANCZOS)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=30))
    
    cover_size = 600
    cover_img_resized = cover_img.resize((cover_size, cover_size), Image.Resampling.LANCZOS)
    
    final_img = Image.new("RGB", (width, height))
    final_img.paste(bg_img, (0, 0))
    
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 100))
    final_img.paste(mask, (0, 0), mask)
    final_img.paste(cover_img_resized, ((width - cover_size) // 2, 200))

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

    draw_text_center(850, f"《{music['name']}》", font_title, (255, 255, 255))
    draw_text_center(930, f"- {music['artist']} -", font_artist, (200, 200, 200))
    draw_text_center(1100, f"🎵 {date_str} 每日推歌", font_date, (255, 255, 255))

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
            <p style="margin: 5px 0; font-size: 17px; color: #2c3e50;"><strong>🎵 歌名：</strong>{music['name']}</p>
            <p style="margin: 5px 0; font-size: 16px; color: #7f8c8d;"><strong>🎤 歌手：</strong>{music['artist']}</p>
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
    
    # 1. 抓取音乐
    music = get_music_data()
    print(f"🎵 成功获取歌曲: {music['name']} - {music['artist']}")
    
    # 2. 调用 Gemini 生成标题和文案
    print("🤖 正在呼叫 Gemini 生成文案...")
    ai_title, ai_content = generate_content_with_gemini(music['name'], music['artist'])
    print(f"✨ 标题: {ai_title}")
    
    # 3. 生成图片
    img_url = generate_cover(music)
    print(f"🖼️ 图片已生成: {img_url}")
    
    # 4. 生成排版并保存
    html_str = generate_wechat_html(music, img_url, ai_content)
    save_json(ai_title, img_url, html_str)
    print("✅ JSON 与 HTML 更新完成！")
