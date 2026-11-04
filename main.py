import os
import time
import sqlite3
import hashlib
import threading
from flask import Flask, request, jsonify
import discord
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("ACCOUNT_CHANNEL_ID", 0))

# ==========================================
# FLASK СЕРВЕР + API ДЛЯ ИНЖЕКТОРА
# ==========================================
app = Flask(__name__)

@app.route('/')
def health():
    return "BazaX API is alive", 200

# ЭТОТ ЭНДПОИНТ БУДЕТ ЧИТАТЬ ТВОЙ C++ ИНЖЕКТОР
@app.route('/api/get_info', methods=['GET'])
def get_info():
    key = request.args.get('key')
    hwid = request.args.get('hwid', 'Unknown_Device')
    
    if not key:
        return jsonify({"status": "error", "message": "Key is required"}), 400

    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("SELECT discord_id, plan, cloud_limit, devices FROM users WHERE key = ?", (key,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return jsonify({"status": "error", "message": "Invalid or expired key"}), 401

    discord_id, plan, cloud_limit, devices = row
    
    # Обновляем список устройств (если HWID новый)
    if devices is None:
        devices = hwid
    elif hwid not in devices:
        devices += f", {hwid}"
        
    c.execute("UPDATE users SET devices = ? WHERE key = ?", (devices, key))
    conn.commit()
    conn.close()

    # Определяем функции в зависимости от плана
    if plan == "BOOST":
        features = {
            "internal": True,
            "max_tests": True,
            "beta_test": True,
            "keyless": True,
            "all_functions": True
        }
    else: # FREE
        features = {
            "internal": True,
            "max_tests": True,
            "beta_test": False,
            "keyless": True,
            "all_functions": False
        }

    # Отдаем инфу инжектору
    return jsonify({
        "status": "success",
        "plan": plan,
        "cloud_limit_mb": cloud_limit,
        "features": features,
        "hwid_registered": hwid
    })

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# БАЗА ДАННЫХ
# ==========================================
def init_db():
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        discord_id TEXT PRIMARY KEY,
        plan TEXT,
        key TEXT UNIQUE,
        cloud_limit INTEGER,
        devices TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS deleted_users (
        discord_id TEXT PRIMARY KEY,
        delete_time INTEGER
    )''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("SELECT plan, key, cloud_limit, devices FROM users WHERE discord_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    return row

def set_user(user_id, plan, key, cloud_limit, devices=""):
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?)", 
              (str(user_id), plan, key, cloud_limit, devices))
    c.execute("DELETE FROM deleted_users WHERE discord_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE discord_id = ?", (str(user_id),))
    c.execute("INSERT OR REPLACE INTO deleted_users VALUES (?, ?)", (str(user_id), int(time.time())))
    conn.commit()
    conn.close()

def check_cooldown(user_id):
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("SELECT delete_time FROM deleted_users WHERE discord_id = ?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    
    if row:
        delete_time = row[0]
        now = int(time.time())
        if now - delete_time < 86400:
            remaining = 86400 - (now - delete_time)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            return False, f"{hours}h {minutes}m"
    return True, ""

init_db()

# ==========================================
# DISCORD БОТ
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

class AccountView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create", style=discord.ButtonStyle.success, custom_id="btn_create")
    async def btn_create(self, interaction: discord.Interaction, button: Button):
        user = get_user(interaction.user.id)
        if user:
            await interaction.response.send_message("❌ Ты уже привязал аккаунт.", ephemeral=True)
            return
        
        can_create, time_left = check_cooldown(interaction.user.id)
        if not can_create:
            await interaction.response.send_message(f"⏳ Ты удалил аккаунт. Повторная регистрация доступна через **{time_left}**.", ephemeral=True)
            return
        
        key = "BAZAX-" + hashlib.md5(f"{interaction.user.id}-{time.time()}".encode()).hexdigest()[:16].upper()
        set_user(interaction.user.id, "FREE", key, 5)
        
        embed = discord.Embed(title="✅ Аккаунт создан", color=0x00FF00)
        embed.add_field(name="Твой ключ", value=f"`{key}`", inline=False)
        embed.add_field(name="План", value="FREE (5 MB Cloud)", inline=True)
        embed.set_footer(text="Вставь этот ключ в BazaX Injector.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Cloud Limit", style=discord.ButtonStyle.primary, custom_id="btn_cloud")
    async def btn_cloud(self, interaction: discord.Interaction, button: Button):
        user = get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ Сначала нажми `Create`.", ephemeral=True)
            return
        
        limit = user[2]
        # В реальности нужно брать реальный размер из облака, пока имитируем 0
        used_mb = 0
        percent = int((used_mb / limit) * 100) if limit > 0 else 0
        
        filled = int(percent / 10)
        empty = 10 - filled
        bar = "🟩" * filled + "⬛" * empty
        
        embed = discord.Embed(title="☁️ Cloud Storage", color=0x5865F2)
        embed.add_field(name=f"Usage: {used_mb} MB / {limit} MB", value=f"`{bar}` {percent}%", inline=False)
        
        if limit == 5:
            embed.set_footer(text="Upgrade to BOOST to get 100 MB!")
            
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Your Plan", style=discord.ButtonStyle.secondary, custom_id="btn_plan")
    async def btn_plan(self, interaction: discord.Interaction, button: Button):
        user = get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ Сначала нажми `Create`.", ephemeral=True)
            return
        
        plan = user[0]
        if plan == "FREE":
            desc = "5 MB Cloud\nInternal Injector\nStandard Tests\nKeyless (rotates every 30 days)\n❌ Beta Features"
        else:
            desc = "100 MB Cloud\nInternal Injector\nAll Tests\nKeyless (Forever)\n✅ Beta Features Unblocked"
            
        embed = discord.Embed(title=f"💎 Твой план: {plan}", description=desc, color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Devices", style=discord.ButtonStyle.secondary, custom_id="btn_devices")
    async def btn_devices(self, interaction: discord.Interaction, button: Button):
        user = get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ Сначала нажми `Create`.", ephemeral=True)
            return
        
        devices = user[3] if user[3] else "Нет привязанных устройств."
        await interaction.response.send_message(f"🖥️ **Устройства:**\n{devices}", ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="btn_delete")
    async def btn_delete(self, interaction: discord.Interaction, button: Button):
        user = get_user(interaction.user.id)
        if not user:
            await interaction.response.send_message("❌ У тебя нет аккаунта.", ephemeral=True)
            return
            
        delete_user(interaction.user.id)
        await interaction.response.send_message("🗑️ Аккаунт удален. Повторная регистрация будет доступна через **24 часа**.", ephemeral=True)

@bot.event
async def on_ready():
    print(f"[+] Бот {bot.user} запущен!")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        async for message in channel.history(limit=10):
            if message.author == bot.user:
                await message.delete()

        embed = discord.Embed(
            title="**ACCOUNT**", 
            description="Your system is already open here! Where do we start?", 
            color=0x2b2d31
        )
        await channel.send(embed=embed, view=AccountView())
        print(f"[+] Сообщение с кнопками отправлено в канал {channel.name}")

# ==========================================
# ТОЧКА ВХОДА
# ==========================================
if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    print("[*] Запуск бота и API...")
    bot.run(TOKEN)
