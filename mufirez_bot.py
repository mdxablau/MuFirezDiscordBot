import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone

# =========================
# CONFIG
# =========================
# Invasion schedule times are based on GMT-3 (Brazil time)
INVASION_TZ = timezone(timedelta(hours=-3))

DISCORD_CHANNEL_ID = 1493841667231449210
FARMERS_ROLE_ID = 1493850248488161321

# Reminder times (minutes before invasion)
REMINDER_MINUTES = [1]

# Duplicate protection
sent_reminders = set()

# =========================
# MANUAL INVASION SCHEDULE
# =========================
INVASION_SCHEDULE = {
    "Golden": ["02:15", "06:15", "10:15", "14:15", "18:15", "22:15"],
    "Skeleton King": ["03:15", "07:15", "11:15", "15:15", "19:15", "23:15"],
    "Red Dragon": ["01:30", "05:30", "09:30", "13:30", "17:30", "21:30"],
    "Ice Queen": ["00:30", "04:30", "08:30", "12:30", "16:30", "20:30"],
    "Balrog": ["02:30", "06:30", "10:30", "14:30", "18:30", "22:30"],
    "Hydra": ["01:15", "05:15", "09:15", "13:15", "17:15", "21:15"],
    "Zaikan": ["00:15", "04:15", "08:15", "12:15", "16:15", "20:15"],
    "Gorgon": ["03:30", "07:30", "11:30", "15:30", "19:30", "23:30"],
    "Tiger": ["00:00", "06:00", "12:00", "18:00"],
    "Sheep": ["01:00", "07:00", "13:00", "19:00"],
    "Rat": ["02:00", "08:00", "14:00", "20:00"],
    "Buffalo": ["04:00", "10:00", "16:00", "22:00"],
    "Rabbit": ["05:00", "11:00", "17:00", "23:00"],
    "Chiken": [
        "00:40", "01:40", "02:40", "03:40", "04:40", "05:40",
        "06:40", "07:40", "08:40", "09:40", "10:40", "11:40",
        "12:40", "13:40", "14:40", "15:40", "16:40", "17:40",
        "18:40", "19:40", "20:40", "21:40", "22:40", "23:40"
    ],
    "Dark Evolution": ["00:20", "09:20", "14:20", "22:20"],
    "Elite": ["00:05", "04:05", "08:05", "12:05", "16:05", "20:05"]
}

# =========================
# DISCORD SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# TIME HELPERS
# =========================
def get_now_gmt3():
    return datetime.now(INVASION_TZ)

def parse_time_today(time_str):
    now = get_now_gmt3()
    hour, minute = map(int, time_str.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

def get_next_spawn_for_invasion(name):
    now = get_now_gmt3()
    times = INVASION_SCHEDULE.get(name, [])

    candidates = []

    for t in times:
        spawn_today = parse_time_today(t)

        if spawn_today > now:
            candidates.append(spawn_today)
        else:
            candidates.append(spawn_today + timedelta(days=1))

    if not candidates:
        return None

    return min(candidates)

def get_all_next_invasions():
    results = []

    for name in INVASION_SCHEDULE.keys():
        next_spawn = get_next_spawn_for_invasion(name)
        if next_spawn:
            results.append((name, next_spawn))

    results.sort(key=lambda x: x[1])
    return results

def format_remaining(target_dt):
    now = get_now_gmt3()
    diff = target_dt - now

    total_seconds = int(diff.total_seconds())
    if total_seconds < 0:
        total_seconds = 0

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    return f"{hours:02}:{minutes:02}:{seconds:02}"

# =========================
# COMMANDS
# =========================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Pong!")

@bot.command()
async def invasion(ctx):
    next_invasions = get_all_next_invasions()[:10]

    if not next_invasions:
        await ctx.send("No invasion timers found.")
        return

    lines = ["⚔️ **Mu Firez - Next Invasion Timers (GMT-3)**\n"]

    for name, spawn_time in next_invasions:
        remaining = format_remaining(spawn_time)
        lines.append(
            f"• **{name}** ➜ {spawn_time.strftime('%H:%M:%S')} "
            f"(**in {remaining}**)"
        )

    lines.append("\nTimes shown are based on your custom invasion schedule (GMT-3)")
    await ctx.send("\n".join(lines))

# =========================
# AUTO REMINDER LOOP
# =========================
@tasks.loop(seconds=1)
async def auto_invasion_reminder_loop():
    channel = bot.get_channel(DISCORD_CHANNEL_ID)

    if not channel:
        print("Could not find channel. Check DISCORD_CHANNEL_ID.")
        return

    now = get_now_gmt3()

    for invasion_name, times in INVASION_SCHEDULE.items():
        for time_str in times:
            spawn_dt = parse_time_today(time_str)

            # If today's time already passed, skip it
            if spawn_dt <= now:
                continue

            diff_seconds = (spawn_dt - now).total_seconds()

            # Check only 1-minute reminder
            for minutes_before in REMINDER_MINUTES:
                target_seconds = minutes_before * 60

                # 2-second safe window (better for Railway)
                if target_seconds - 2 < diff_seconds <= target_seconds:
                    reminder_key = f"{invasion_name}|{spawn_dt.isoformat()}|{minutes_before}"

                    if reminder_key not in sent_reminders:
                        sent_reminders.add(reminder_key)

                        role_mention = f"<@&{FARMERS_ROLE_ID}>"

                        message = (
                            f"{role_mention}\n"
                            f"⚔️ **Mu Firez Invasion Reminder**\n"
                            f"**{invasion_name}** starts in **1 minute!**\n"
                            f"🕒 Spawn Time: **{spawn_dt.strftime('%H:%M:%S GMT-3')}**"
                        )

                        try:
                            await channel.send(message)
                            print(f"Reminder sent: {invasion_name} - 1 min")
                        except Exception as e:
                            print(f"Failed to send reminder: {e}")

    cleanup_old_reminders()

def cleanup_old_reminders():
    now = get_now_gmt3()
    to_remove = []

    for key in sent_reminders:
        try:
            parts = key.split("|")
            spawn_dt = datetime.fromisoformat(parts[1])

            if spawn_dt.tzinfo is None:
                spawn_dt = spawn_dt.replace(tzinfo=INVASION_TZ)

            # Remove reminder records 2 hours after spawn
            if now - spawn_dt > timedelta(hours=2):
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
    print("Mu Firez Invasion Bot is online!")
    print("Using manual invasion schedule (GMT-3)")
    print("Reminder mode: 1 minute only")

    if not auto_invasion_reminder_loop.is_running():
        auto_invasion_reminder_loop.start()

# =========================
# START BOT
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set.")

bot.run(TOKEN)
