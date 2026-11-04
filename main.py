import os
import time
import sqlite3
import hashlib
import threading
from flask import Flask

import discord
from discord.ext import commands
from discord.ui import Button, View
from dotenv import load_dotenv

# Загружаем переменные (локально из .env, на Render из Environment Variables)
load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = int(os.getenv("ACCOUNT_CHANNEL_ID", 0))

# ==========================================
# FLASK СЕРВЕР ДЛЯ RENDER (Чтобы не засыпал)
# ==========================================
app = Flask(__name__)

@app.route('/')
def health():
    return "BazaX Bot is alive", 200

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
        key TEXT,
        cloud_limit INTEGER,
        devices TEXT
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
    conn.commit()
    conn.close()

def delete_user(user_id):
    conn = sqlite3.connect("bazax_users.db")
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE discord_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

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
        
        await interaction.response.send_message(f"☁️ Твой лимит облака: **{user[2]} MB**", ephemeral=True)

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
        await interaction.response.send_message("🗑️ Аккаунт удален, данные стерты.", ephemeral=True)

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
    else:
        print("[!] Ошибка: Канал не найден. Проверь ID канала и права бота.")

# ==========================================
# ТОЧКА ВХОДА
# ==========================================
if __name__ == "__main__":
    # Запускаем Flask в фоне
    threading.Thread(target=run_web, daemon=True).start()
    # Запускаем бота
    print("[*] Запуск бота...")
    bot.run(TOKEN)
