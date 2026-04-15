import os
import discord
from discord.ext import commands, tasks
import requests
import json
import urllib3
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!"
API_URL = "https://api.mufirez.net/api/events"
SETTINGS_FILE = "bot_settings.json"

# How many results to show per command
EVENT_LIMIT = 10
BOSS_LIMIT = 10
INVASION_LIMIT = 10

# Alert window (minutes before spawn)
ALERT_MINUTES_BEFORE = 5

# Hide SSL warning because Mu Firez API certificate is not set up properly
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# =========================
# DISCORD BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =========================
# SETTINGS STORAGE
# =========================
settings = {
    "alerts_enabled": False,
    "alert_channel_id": None,
    "sent_alerts": []
}

def load_settings():
    global settings
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except:
        save_settings()

def save_settings():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)

# =========================
# API FUNCTIONS
# =========================
def fetch_mufirez_events():
    headers = {
        "Origin": "https://launcher.mufirez.net",
        "Referer": "https://launcher.mufirez.net/",
        "User-Agent": "mufirez/1.0.29"
    }

    response = requests.get(API_URL, headers=headers, timeout=15, verify=False)
    response.raise_for_status()

    outer = response.json()

    if not outer.get("success"):
        return None

    data_field = outer["data"]

    if isinstance(data_field, str):
        inner = json.loads(data_field)
    else:
        inner = data_field

    return inner

def parse_next_occurrence(date_string):
    try:
        return datetime.fromisoformat(date_string.replace("Z", "+00:00"))
    except:
        return None

def format_countdown(target_dt):
    if not target_dt:
        return "unknown"

    now = datetime.now(timezone.utc)
    diff = target_dt - now
    total_seconds = int(diff.total_seconds())

    if total_seconds <= 0:
        return "now"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []

    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    if not parts:
        parts.append("less than 1m")

    return "in " + " ".join(parts)

def format_utc_time(target_dt):
    if not target_dt:
        return "unknown"
    return target_dt.strftime("%Y-%m-%d %H:%M UTC")

def get_items_by_category(category_name, limit=10):
    data = fetch_mufirez_events()
    if not data:
        return []

    events = data.get("events", [])

    filtered = [
        e for e in events
        if e.get("category", "").lower() == category_name.lower()
    ]

    filtered.sort(
        key=lambda x: parse_next_occurrence(x["nextOccurrence"]) or datetime.max.replace(tzinfo=timezone.utc)
    )

    return filtered[:limit]

def get_all_items():
    data = fetch_mufirez_events()
    if not data:
        return []

    items = data.get("events", [])

    items.sort(
        key=lambda x: parse_next_occurrence(x["nextOccurrence"]) or datetime.max.replace(tzinfo=timezone.utc)
    )

    return items

def build_embed(title, items, footer_text):
    if not items:
        return None

    lines = []

    for e in items:
        dt = parse_next_occurrence(e["nextOccurrence"])
        utc_text = format_utc_time(dt)
        countdown_text = format_countdown(dt)

        lines.append(
            f"• **{e['name']}**\n"
            f"  ⏰ `{utc_text}`\n"
            f"  🕒 `{countdown_text}`"
        )

    embed = discord.Embed(
        title=title,
        description="\n\n".join(lines),
        color=discord.Color.red()
    )
    embed.set_footer(text=footer_text)
    return embed

# =========================
# ALERT HELPERS
# =========================
def cleanup_old_alerts():
    if len(settings["sent_alerts"]) > 300:
        settings["sent_alerts"] = settings["sent_alerts"][-300:]
        save_settings()

def should_alert(item):
    dt = parse_next_occurrence(item["nextOccurrence"])
    if not dt:
        return False, None

    now = datetime.now(timezone.utc)
    diff_minutes = (dt - now).total_seconds() / 60

    if 4.0 <= diff_minutes <= 5.9:
        unique_key = f"{item['category']}|{item['name']}|{item['nextOccurrence']}"
        if unique_key not in settings["sent_alerts"]:
            return True, unique_key

    return False, None

def build_alert_message(item):
    dt = parse_next_occurrence(item["nextOccurrence"])
    utc_text = format_utc_time(dt)

    category = item.get("category", "Unknown")
    name = item.get("name", "Unknown")

    if category.lower() == "boss":
        icon = "👑"
        action = "spawns"
    elif category.lower() == "invasion":
        icon = "⚔️"
        action = "starts"
    else:
        icon = "🔥"
        action = "starts"

    return (
        f"{icon} **{name}** ({category}) {action} in **{ALERT_MINUTES_BEFORE} minutes!**\n"
        f"⏰ `{utc_text}`"
    )

# =========================
# BACKGROUND TASK
# =========================
@tasks.loop(minutes=1)
async def auto_alert_loop():
    if not settings.get("alerts_enabled"):
        return

    channel_id = settings.get("alert_channel_id")
    if not channel_id:
        return

    channel = bot.get_channel(channel_id)
    if channel is None:
        return

    try:
        items = get_all_items()
        if not items:
            return

        cleanup_old_alerts()

        for item in items:
            alert, unique_key = should_alert(item)

            if alert:
                message = build_alert_message(item)
                await channel.send(message)

                settings["sent_alerts"].append(unique_key)
                save_settings()

    except Exception as ex:
        print(f"[AUTO ALERT ERROR] {ex}")

# =========================
# BOT EVENTS
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Mu Firez Timer Bot is online!")

    load_settings()

    if not auto_alert_loop.is_running():
        auto_alert_loop.start()

# =========================
# BOT COMMANDS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@bot.command()
async def events(ctx):
    try:
        event_list = get_items_by_category("Events", limit=EVENT_LIMIT)

        if not event_list:
            await ctx.send("❌ Could not fetch Mu Firez event timers.")
            return

        embed = build_embed(
            "🔥 Mu Firez - Next Event Timers",
            event_list,
            "Times shown in UTC + live countdown from Mu Firez API"
        )

        await ctx.send(embed=embed)

    except Exception as ex:
        await ctx.send(f"❌ Error fetching events: `{ex}`")

@bot.command()
async def boss(ctx):
    try:
        boss_list = get_items_by_category("Boss", limit=BOSS_LIMIT)

        if not boss_list:
            await ctx.send("❌ Could not fetch Mu Firez boss timers.")
            return

        embed = build_embed(
            "👑 Mu Firez - Next Boss Timers",
            boss_list,
            "Times shown in UTC + live countdown from Mu Firez API"
        )

        await ctx.send(embed=embed)

    except Exception as ex:
        await ctx.send(f"❌ Error fetching boss timers: `{ex}`")

@bot.command()
async def invasion(ctx):
    try:
        invasion_list = get_items_by_category("Invasion", limit=INVASION_LIMIT)

        if not invasion_list:
            await ctx.send("❌ Could not fetch Mu Firez invasion timers.")
            return

        embed = build_embed(
            "⚔️ Mu Firez - Next Invasion Timers",
            invasion_list,
            "Times shown in UTC + live countdown from Mu Firez API"
        )

        await ctx.send(embed=embed)

    except Exception as ex:
        await ctx.send(f"❌ Error fetching invasion timers: `{ex}`")

@bot.command()
async def all(ctx):
    try:
        events_list = get_items_by_category("Events", limit=5)
        boss_list = get_items_by_category("Boss", limit=5)
        invasion_list = get_items_by_category("Invasion", limit=5)

        embed = discord.Embed(
            title="🔥 Mu Firez - All Timers Overview",
            color=discord.Color.red()
        )

        if events_list:
            event_lines = []
            for e in events_list:
                dt = parse_next_occurrence(e["nextOccurrence"])
                event_lines.append(f"• **{e['name']}** → `{format_countdown(dt)}`")
            embed.add_field(name="📅 Events", value="\n".join(event_lines), inline=False)
        else:
            embed.add_field(name="📅 Events", value="No data", inline=False)

        if boss_list:
            boss_lines = []
            for e in boss_list:
                dt = parse_next_occurrence(e["nextOccurrence"])
                boss_lines.append(f"• **{e['name']}** → `{format_countdown(dt)}`")
            embed.add_field(name="👑 Boss", value="\n".join(boss_lines), inline=False)
        else:
            embed.add_field(name="👑 Boss", value="No data", inline=False)

        if invasion_list:
            invasion_lines = []
            for e in invasion_list:
                dt = parse_next_occurrence(e["nextOccurrence"])
                invasion_lines.append(f"• **{e['name']}** → `{format_countdown(dt)}`")
            embed.add_field(name="⚔️ Invasion", value="\n".join(invasion_lines), inline=False)
        else:
            embed.add_field(name="⚔️ Invasion", value="No data", inline=False)

        embed.set_footer(text="Live countdown from Mu Firez API")

        await ctx.send(embed=embed)

    except Exception as ex:
        await ctx.send(f"❌ Error fetching all timers: `{ex}`")

@bot.command()
async def setalerts(ctx):
    settings["alert_channel_id"] = ctx.channel.id
    save_settings()
    await ctx.send(f"✅ Auto reminder channel set to {ctx.channel.mention}")

@bot.command()
async def status(ctx):
    enabled = settings.get("alerts_enabled", False)
    channel_id = settings.get("alert_channel_id")

    if channel_id:
        channel_text = f"<#{channel_id}>"
    else:
        channel_text = "Not set"

    embed = discord.Embed(
        title="🔔 Auto Reminder Status",
        color=discord.Color.green() if enabled else discord.Color.orange()
    )
    embed.add_field(name="Alerts Enabled", value=str(enabled), inline=False)
    embed.add_field(name="Alert Channel", value=channel_text, inline=False)
    embed.add_field(name="Alert Time", value=f"{ALERT_MINUTES_BEFORE} minutes before spawn", inline=False)
    embed.set_footer(text="Use !setalerts, !alerts on, !alerts off")

    await ctx.send(embed=embed)

@bot.command()
async def alerts(ctx, mode=None):
    if mode is None:
        await ctx.send("Usage: `!alerts on` or `!alerts off`")
        return

    mode = mode.lower()

    if mode == "on":
        if not settings.get("alert_channel_id"):
            await ctx.send("❌ Set an alert channel first with `!setalerts`")
            return

        settings["alerts_enabled"] = True
        save_settings()
        await ctx.send("✅ Auto reminders are now **ON**")

    elif mode == "off":
        settings["alerts_enabled"] = False
        save_settings()
        await ctx.send("🛑 Auto reminders are now **OFF**")

    else:
        await ctx.send("Usage: `!alerts on` or `!alerts off`")

# =========================
# START BOT
# =========================
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set.")

bot.run(TOKEN)