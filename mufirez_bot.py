import os
import json
import requests
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

# =========================
# CONFIG
# =========================
API_URL = "https://api.mufirez.net/api/events"
SETTINGS_FILE = "bot_settings.json"

# In-memory cache + duplicate protection
cached_events = []
sent_reminders = set()

# Reminder schedule (minutes before event)
REMINDER_MINUTES = [5, 3, 1]

# =========================
# LOAD SETTINGS
# =========================
def load_settings():
    default_settings = {
        "timezone": "UTC",
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
    possible_keys = [
        "startAt",
        "start_at",
        "date",
        "datetime",
        "time",
        "nextSpawn",
        "next_spawn",
        "nextOccurrence"
    ]

    for key in possible_keys:
        if key in event and event[key]:
            raw = str(event[key]).strip()

            if raw.endswith("Z"):
                raw = raw.replace("Z", "+00:00")

            try:
                return datetime.fromisoformat(raw)
            except:
                pass

    return None

# =========================
# EVENT HELPERS
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

    if category == "Unknown":
        category = event.get("type") or event.get("category") or "Unknown"

    return str(category)

def get_next_by_category(category_name, limit=10):
    filtered = []

    for event in cached_events:
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

    lines.append("\nTimes shown are from Mu Firez API cache (UTC)")
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

    lines.append("\nTimes shown are from Mu Firez API cache (UTC)")
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

    lines.append("\nTimes shown are from Mu Firez API cache (UTC)")
    await ctx.send("\n".join(lines))

# =========================
# FETCH LOOP (LOW API SPAM)
# =========================
@tasks.loop(seconds=30)
async def refresh_event_cache():
    global cached_events

    data = fetch_mufirez_events()
    if data:
        cached_events = data
        print(f"Cache refreshed: {len(cached_events)} events loaded")
    else:
        print("Cache refresh returned no data (keeping old cache if available)")

@refresh_event_cache.before_loop
async def before_refresh_event_cache():
    await bot.wait_until_ready()

# =========================
# REMINDER LOOP (USES CACHE)
# =========================
@tasks.loop(seconds=1)
async def auto_reminder_loop():
    channel_id = settings.get("discord_channel_id", 0)
    farmers_role_id = settings.get("farmers_role_id", 0)
    enabled_categories = settings.get("enabled_categories", {})

    if not channel_id:
        print("No discord_channel_id set in bot_settings.json")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print("Could not find channel. Check discord_channel_id.")
        return

    now = datetime.now(timezone.utc)

    for event in cached_events:
        name = get_event_name(event)
        category = get_event_category(event)
        dt = parse_event_time(event)

        if not dt:
            continue

        if not enabled_categories.get(category, False):
            continue

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        diff_seconds = (dt - now).total_seconds()

        # Skip already passed events
        if diff_seconds <= 0:
            continue

        # Check each reminder time (5, 3, 1 minutes)
        for minutes_before in REMINDER_MINUTES:
            target_seconds = minutes_before * 60

            # 30-second safe window to avoid missing reminder due to cache timing
            if target_seconds - 30 < diff_seconds <= target_seconds:
                reminder_key = f"{category}|{name}|{dt.isoformat()}|{minutes_before}"

                if reminder_key not in sent_reminders:
                    sent_reminders.add(reminder_key)

                    role_mention = f"<@&{farmers_role_id}>" if farmers_role_id else "@Farmers"

                    message = (
                        f"{role_mention}\n"
                        f"⏰ **Mu Firez Reminder**\n"
                        f"**{name}** ({category}) starts in **{minutes_before} minute{'s' if minutes_before != 1 else ''}!**\n"
                        f"🕒 Spawn Time: **{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}**"
                    )

                    try:
                        await channel.send(message)
                        print(f"Reminder sent: {name} ({category}) - {minutes_before} min")
                    except Exception as e:
                        print(f"Failed to send reminder: {e}")

    cleanup_old_reminders()

def cleanup_old_reminders():
    now = datetime.now(timezone.utc)

    to_remove = []
    for key in sent_reminders:
        try:
            parts = key.split("|")
            dt = datetime.fromisoformat(parts[2])

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # Remove old reminder records 2 hours after event
            if now - dt > timedelta(hours=2):
                to_remove.append(key)
        except:
            to_remove.append(key)

    for key in to_remove:
        sent_reminders.discard(key)

# =========================
# BOT READY
# =========================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("Mu Firez Timer Bot is online!")

    if not refresh_event_cache.is_running():
        refresh_event_cache.start()

    if not auto_reminder_loop.is_running():
        auto_reminder_loop.start()

    # Prime cache immediately on startup
    global cached_events
    initial_data = fetch_mufirez_events()
    if initial_data:
        cached_events = initial_data
        print(f"Initial cache loaded: {len(cached_events)} events")
    else:
        print("Initial cache load failed")

    print("Auto reminder loop started.")

# =========================
# START BOT
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set.")

bot.run(TOKEN)
