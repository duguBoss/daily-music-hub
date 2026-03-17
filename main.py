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

# 获取 GitHub 环境变量 (用于拼接图片直链)
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "your_username/your_repo")
BRANCH = "main"

# ================= 1. 每周清空机制 =================
def clean_weekly():
    today = datetime.now()
    # weekday() 返回 0-6，0 代表周一。如果是周一，清空 outputs 文件夹
    if today.weekday() == 0:
        if os.path.exists("outputs"):
            shutil.rmtree("outputs")
            print("今天是周一，已清空历史生成的图片和数据。")
    
    os.makedirs("outputs/images", exist_ok=True)

# ================= 2. 获取音乐数据 =================
def get_music_data():
    # 这里为了稳定性，使用一个免费随机网易云API，如果失败则使用保底数据
    try:
        res = requests.get("https://api.uomg.com/api/rand.music?sort=热歌榜&format=json", timeout=10).json()
        if res.get("code") == 1:
            data = res["data"]
            return {
                "name": data["name"],
                "artist": data["artistsname"],
                "picUrl": data["picurl"],
                "url": data["url"]
            }
    except Exception as e:
        print(f"API 请求失败，使用保底数据: {e}")
        
    return {
        "name": "海底",
        "artist": "一支榴莲",
        "picUrl": "https://p1.music.126.net/rINn3QJkH7nK_1r3K2k9VQ==/109951164803767222.jpg",
        "url": "https://music.163.com/#/song?id=1433541241"
    }

# ================= 3. 生成 3:4 (宽900x高1200) 竖屏卡片 =================
def generate_cover(music):
    width, height = 900, 1200
    date_str = datetime.now().strftime("%Y-%m-%d")
    img_filename = f"{date_str}.jpg"
    img_path = f"outputs/images/{img_filename}"

    # 下载封面原图
    response = requests.get(music['picUrl'])
    cover_img = Image.open(BytesIO(response.content)).convert("RGB")
    
    # 制作背景：放大并高斯模糊
    bg_img = cover_img.resize((width, width))
    bg_img = bg_img.resize((width, height), Image.Resampling.LANCZOS)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=30))
    
    # 将原封面贴在中间
    cover_size = 600
    cover_img_resized = cover_img.resize((cover_size, cover_size), Image.Resampling.LANCZOS)
    
    # 画布组合
    final_img = Image.new("RGB", (width, height))
    final_img.paste(bg_img, (0, 0))
    
    # 添加半透明遮罩让文字更清晰
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 100))
    final_img.paste(mask, (0, 0), mask)
    
    final_img.paste(cover_img_resized, ((width - cover_size) // 2, 200))

    # 写字
    draw = ImageDraw.Draw(final_img)
    try:
        font_title = ImageFont.truetype("font.ttf", 60)
        font_artist = ImageFont.truetype("font.ttf", 40)
        font_date = ImageFont.truetype("font.ttf", 35)
    except:
        # 如果没有字体文件，使用默认（将无法显示中文）
        font_title = font_artist = font_date = ImageFont.load_default()

    # 居中文字辅助函数
    def draw_text_center(y, text, font, color):
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), text, font=font, fill=color)

    draw_text_center(850, f"《{music['name']}》", font_title, (255, 255, 255))
    draw_text_center(930, f"- {music['artist']} -", font_artist, (200, 200, 200))
    draw_text_center(1100, f"🎵 {date_str} 每日推歌", font_date, (255, 255, 255))

    final_img.save(img_path, quality=95)
    
    # 生成 GitHub Raw 直链
    github_raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{BRANCH}/outputs/images/{img_filename}"
    return github_raw_url

# ================= 4. 生成微信算法推荐优化的 HTML =================
def generate_wechat_html(music, img_url):
    # 针对微信算法的文案模板（包含情绪价值、互动引导）
    copywriting = [
        "耳机一戴，谁也不爱。这首歌的前奏一响，瞬间就被拉回了那个特别的时刻。",
        "今天为大家挖到了一首宝藏神曲，副歌部分简直是灵魂暴击，强烈建议单曲循环！",
        "有些歌，听的是旋律；有些歌，听的是自己。这首曲子里的故事，你听懂了吗？"
    ]
    
    html_content = f"""
    <section style="box-sizing: border-box; max-width: 100%; letter-spacing: 1px; font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; background-color: #ffffff; padding: 10px;">
        <!-- 顶部引导 GIF -->
        <p style="text-align: center; margin-bottom: 20px;">
            <img src="{TOP_GIF}" style="width: 100%; max-width: 600px; display: inline-block;" />
        </p>

        <!-- 标题区域 -->
        <section style="margin: 20px 0; text-align: center;">
            <h2 style="font-size: 22px; color: #333333; margin: 0; padding-bottom: 10px; border-bottom: 2px solid #e0e0e0; display: inline-block;">
                今日份宝藏音乐掉落 🎧
            </h2>
        </section>

        <!-- 歌曲信息卡片 -->
        <section style="background-color: #f7f9fa; border-radius: 12px; padding: 20px; margin: 20px 0; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
            <p style="margin: 5px 0; font-size: 17px; color: #2c3e50;"><strong>🎵 歌名：</strong>{music['name']}</p>
            <p style="margin: 5px 0; font-size: 16px; color: #7f8c8d;"><strong>🎤 歌手：</strong>{music['artist']}</p>
        </section>

        <!-- 海报图片 -->
        <p style="text-align: center; margin: 25px 0;">
            <img src="{img_url}" style="width: 100%; max-width: 500px; border-radius: 16px; box-shadow: 0 8px 20px rgba(0,0,0,0.15);" />
        </p>

        <!-- 微信推荐算法文案 (情感共鸣) -->
        <section style="margin: 30px 0;">
            <p style="font-size: 16px; color: #555555; line-height: 1.8; text-indent: 2em; margin-bottom: 15px;">
                {random.choice(copywriting)}
            </p>
            <p style="font-size: 16px; color: #555555; line-height: 1.8; text-indent: 2em;">
                喜欢的家人们记得长按保存上方的高清分享壁纸，发朋友圈或者设为屏保都超有质感！别忘了在评论区分享你今天的心情哦~
            </p>
        </section>

        <!-- 底部引导 GIF -->
        <p style="text-align: center; margin-top: 40px;">
            <img src="{BOTTOM_GIF}" style="width: 100%; max-width: 600px; display: inline-block;" />
        </p>
    </section>
    """
    return html_content

# ================= 5. 保存并更新 JSON =================
def save_json(title, img_url, html):
    json_path = "outputs/daily_post.json"
    
    # 读取已有数据（如果是数组格式）
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
    
    # 添加到列表头部
    data_list.insert(0, new_data)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data_list, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    clean_weekly()
    music = get_music_data()
    print(f"今日抓取歌曲: {music['name']} - {music['artist']}")
    
    img_url = generate_cover(music)
    print(f"图片已生成，预计链接: {img_url}")
    
    html_str = generate_wechat_html(music, img_url)
    
    title = f"今日分享 | 听到这首《{music['name']}》，整个人都被治愈了"
    save_json(title, img_url, html_str)
    print("JSON 与 HTML 更新完成！")
