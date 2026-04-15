import os
import json
import asyncio
import requests
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

# =========================
# CONFIG
# =========================
API_URL = "https://api.mufirez.net/api/events"
SETTINGS_FILE = "bot_settings.json"

# Keeps track of reminders already sent (prevents duplicates)
sent_reminders = set()

# =========================
# LOAD SETTINGS
# =========================
def load_settings():
    default_settings = {
        "timezone": "UTC",
        "notify_minutes_before": 5,
        "discord_channel_id": 1493841667231449210,
        "farmers_role_id": 1493850248488161321,
        "enabled_categories": {
            "Events": True,
            "Boss": True,
            "Invasion": True
        }
    }

    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, indent=4)
        return default_settings

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

settings = load_settings()

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# API FETCH
# =========================
def fetch_mufirez_events():
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()

        outer = response.json()

        # Handles both formats:
        # 1) {"data": [...]} 
        # 2) {"data": {"events": [...], "boss": [...], "invasion": [...]}}
        data = outer.get("data", [])

        if isinstance(data, dict):
            combined = []

            if "events" in data and isinstance(data["events"], list):
                for item in data["events"]:
                    item["category"] = "Events"
                    combined.append(item)

            if "boss" in data and isinstance(data["boss"], list):
                for item in data["boss"]:
                    item["category"] = "Boss"
                    combined.append(item)

            if "invasion" in data and isinstance(data["invasion"], list):
                for item in data["invasion"]:
                    item["category"] = "Invasion"
                    combined.append(item)

            return combined

        elif isinstance(data, list):
            return data

        return []

    except Exception as e:
        print(f"Error fetching Mu Firez API: {e}")
        return []

# =========================
# DATETIME PARSER
# =========================
def parse_event_time(event):
    # Try common possible keys from API
    possible_keys = [
        "startAt",
        "start_at",
        "date",
        "datetime",
        "time",
        "nextSpawn",
        "next_spawn"
    ]

    for key in possible_keys:
        if key in event and event[key]:
            raw = str(event[key]).strip()

            # Normalize Zulu time
            if raw.endswith("Z"):
                raw = raw.replace("Z", "+00:00")

            try:
                return datetime.fromisoformat(raw)
            except:
                pass

    return None

# =========================
# EVENT NAME / CATEGORY
# =========================
def get_event_name(event):
    return (
        event.get("name")
        or event.get("title")
        or event.get("event")
        or event.get("boss")
        or event.get("monster")
        or "Unknown"
    )

def get_event_category(event):
    category = event.get("category", "Unknown")

    # fallback if API includes type/category field
    if category == "Unknown":
        category = event.get("type") or event.get("category") or "Unknown"

    return str(category)

# =========================
# FORMATTERS
# =========================
def format_timer_line(event):
    name = get_event_name(event)
    category = get_event_category(event)
    dt = parse_event_time(event)

    if not dt:
        return f"- {name} ({category}) -> Unknown time"

    return f"- {name} ({category}) -> {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}"

def get_next_by_category(category_name, limit=10):
    data = fetch_mufirez_events()
    filtered = []

    for event in data:
        category = get_event_category(event).lower()
        if category == category_name.lower():
            dt = parse_event_time(event)
            if dt:
                filtered.append((dt, event))

    filtered.sort(key=lambda x: x[0])
    return [event for _, event in filtered[:limit]]

# =========================
# COMMANDS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@bot.command()
async def events(ctx):
    items = get_next_by_category("Events", 10)

    if not items:
        await ctx.send("No upcoming Events found.")
        return

    lines = ["🔥 **Mu Firez - Next Event Timers**\n"]
    for event in items:
        dt = parse_event_time(event)
        name = get_event_name(event)
        lines.append(f"• {name} ➜ {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    lines.append("\nTimes shown are from Mu Firez API (UTC)")
    await ctx.send("\n".join(lines))

@bot.command()
async def boss(ctx):
    items = get_next_by_category("Boss", 10)

    if not items:
        await ctx.send("No upcoming Boss timers found.")
        return

    lines = ["👑 **Mu Firez - Next Boss Timers**\n"]
    for event in items:
        dt = parse_event_time(event)
        name = get_event_name(event)
        lines.append(f"• {name} ➜ {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    lines.append("\nTimes shown are from Mu Firez API (UTC)")
    await ctx.send("\n".join(lines))

@bot.command()
async def invasion(ctx):
    items = get_next_by_category("Invasion", 15)

    if not items:
        await ctx.send("No upcoming Invasion timers found.")
        return

    lines = ["⚔️ **Mu Firez - Next Invasion Timers**\n"]
    for event in items:
        dt = parse_event_time(event)
        name = get_event_name(event)
        lines.append(f"• {name} ➜ {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    lines.append("\nTimes shown are from Mu Firez API (UTC)")
    await ctx.send("\n".join(lines))

# =========================
# AUTO REMINDER LOOP
# =========================
@tasks.loop(minutes=1)
async def auto_reminder_loop():
    channel_id = settings.get("discord_channel_id", 0)
    farmers_role_id = settings.get("farmers_role_id", 0)
    notify_minutes = settings.get("notify_minutes_before", 5)
    enabled_categories = settings.get("enabled_categories", {})

    if not channel_id:
        print("No discord_channel_id set in bot_settings.json")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print("Could not find channel. Check discord_channel_id.")
        return

    data = fetch_mufirez_events()
    now = datetime.now(timezone.utc)

    for event in data:
        name = get_event_name(event)
        category = get_event_category(event)
        dt = parse_event_time(event)

        if not dt:
            continue

        # Skip disabled categories
        if not enabled_categories.get(category, False):
            continue

        # Ensure timezone aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        diff_seconds = (dt - now).total_seconds()
        diff_minutes = diff_seconds / 60

        # Trigger only if event is within the reminder window
        # (example: between 4.0 and 5.0 minutes before if notify_minutes = 5)
        if notify_minutes - 1 < diff_minutes <= notify_minutes:
            reminder_key = f"{category}|{name}|{dt.isoformat()}|{notify_minutes}"

            if reminder_key in sent_reminders:
                continue

            sent_reminders.add(reminder_key)

            role_mention = f"<@&{farmers_role_id}>" if farmers_role_id else "@farmers"

            message = (
                f"{role_mention}\n"
                f"⏰ **Mu Firez Reminder**\n"
                f"**{name}** ({category}) starts in **{notify_minutes} minutes!**\n"
                f"🕒 Spawn Time: **{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}**"
            )

            try:
                await channel.send(message)
                print(f"Reminder sent: {name} ({category})")
            except Exception as e:
                print(f"Failed to send reminder: {e}")

    # Clean old reminder keys occasionally
    cleanup_old_reminders()

def cleanup_old_reminders():
    # Removes reminders for events that already passed a while ago
    # Keeps memory from growing too much during long uptime
    to_remove = []
    now = datetime.now(timezone.utc)

    for key in sent_reminders:
        try:
            parts = key.split("|")
            dt = datetime.fromisoformat(parts[2])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Remove if older than 2 hours
            if now - dt > timedelta(hours=2):
                to_remove.append(key)
        except:
            to_remove.append(key)

    for key in to_remove:
        sent_reminders.discard(key)

@auto_reminder_loop.before_loop
async def before_auto_reminder_loop():
    await bot.wait_until_ready()
    print("Auto reminder loop started.")

# =========================
# BOT READY
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Mu Firez Timer Bot is online!")

    if not auto_reminder_loop.is_running():
        auto_reminder_loop.start()

# =========================
# START BOT
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set.")

bot.run(TOKEN)
