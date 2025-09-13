# journalist_bot.py
# Discord Journalist Bot — Features:
# - Add/remove/list warnings
# - Jobs with interactive Claim/Unclaim buttons
# - Open-to-all job categories (anyone can claim) — seeded + editable via /openall
# - Weekly interview candidate announcement + ping every 2 days
# - Logs: warnings + job claim/unclaim + job create/close to a log channel
# - SQLite persistence (aiosqlite)

import os
import asyncio
import datetime as dt
from typing import Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks
import aiosqlite
from dotenv import load_dotenv
import logging
logging.basicConfig(level=logging.INFO)   # show discord.py INFO logs


DB_PATH = "journalist_bot.db"

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.guilds = True
INTENTS.message_content = False

# Seed list for open-to-all categories (normalized lowercase)
OPEN_TO_ALL_SEED = {
    "discord announcements",
    "game announcements",
    "staff birthdays",
    "fan group promotions",
    "promo codes",
    "lumbergames",
    "serverboosts",
    "new rankups",
    "community birthdays",
    "wiki fact",
}

class JournalBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=INTENTS,
            help_command=None,
            application_id=None
        )
        self.db: Optional[aiosqlite.Connection] = None
        # use the built-in self.tree from commands.Bot
        self.ping_every_two_days_loop.change_interval(hours=48)
        self.rotate_weekly_loop.change_interval(hours=168)


    async def setup_hook(self):
        self.db = await aiosqlite.connect(DB_PATH)
        await self._init_db()
        await self.tree.sync()
        self.ping_every_two_days_loop.start()
        self.rotate_weekly_loop.start()

    async def _init_db(self):
        await self.db.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT,
                open_to_all INTEGER NOT NULL DEFAULT 0,
                claimed_by INTEGER,
                status TEXT NOT NULL DEFAULT 'open', -- open | claimed | closed
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS interview_rotation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS interview_state (
                guild_id INTEGER PRIMARY KEY,
                current_index INTEGER NOT NULL DEFAULT 0,
                last_rotate_at TEXT
            );

            CREATE TABLE IF NOT EXISTS open_all_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL
            );
            """
        )
        # Best-effort migrations
        try:
            await self.db.execute("ALTER TABLE jobs ADD COLUMN category TEXT")
        except Exception:
            pass
        try:
            await self.db.execute("ALTER TABLE jobs ADD COLUMN open_to_all INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        await self.db.commit()

    # --- settings helpers ---
    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str):
        await self.db.execute("REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))
        await self.db.commit()

    # --- rotation helpers/loops ---
    @tasks.loop(hours=48)
    async def ping_every_two_days_loop(self):
        try:
            general_id = await self.get_setting("general_channel_id")
            if not general_id:
                return
            channel = self.get_channel(int(general_id))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return
            candidate = await self._current_candidate(channel.guild.id)
            if candidate:
                await channel.send(f"⏰ Interview reminder: Next up is {candidate.mention}! (pinging every 2 days)")
        except Exception as e:
            print("[ping_every_two_days_loop]", e)

    @ping_every_two_days_loop.before_loop
    async def _before_ping(self):
        await self.wait_until_ready()

    @tasks.loop(hours=168)  # 7 days
    async def rotate_weekly_loop(self):
        try:
            general_id = await self.get_setting("general_channel_id")
            if not general_id:
                return
            channel = self.get_channel(int(general_id))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                return
            await self._advance_rotation(channel.guild.id)
            candidate = await self._current_candidate(channel.guild.id)
            if candidate:
                await channel.send(f"📣 This week's interview: {candidate.mention}! (will ping every 2 days)")
        except Exception as e:
            print("[rotate_weekly_loop]", e)

    @rotate_weekly_loop.before_loop
    async def _before_rotate(self):
        await self.wait_until_ready()

    async def _current_candidate(self, guild_id: int) -> Optional[discord.Member]:
        async with self.db.execute("SELECT current_index FROM interview_state WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
            index = row[0] if row else 0
        async with self.db.execute("SELECT user_id FROM interview_rotation WHERE guild_id=? ORDER BY id", (guild_id,)) as cur:
            rows = await cur.fetchall()
            if not rows:
                return None
            index %= len(rows)
            user_id = rows[index][0]
        guild = self.get_guild(guild_id)
        return guild.get_member(user_id) if guild else None

    async def _advance_rotation(self, guild_id: int):
        async with self.db.execute("SELECT current_index FROM interview_state WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
        if row:
            new_index = row[0] + 1
            await self.db.execute(
                "UPDATE interview_state SET current_index=?, last_rotate_at=? WHERE guild_id=?",
                (new_index, dt.datetime.utcnow().isoformat(), guild_id)
            )
        else:
            await self.db.execute(
                "INSERT INTO interview_state(guild_id, current_index, last_rotate_at) VALUES(?, 0, ?)",
                (guild_id, dt.datetime.utcnow().isoformat())
            )
        await self.db.commit()

bot = JournalBot()
@bot.event
async def on_connect():
    print("[bot] Connected to Discord gateway")

@bot.event
async def on_ready():
    print(f"[bot] Logged in as {bot.user} (ID: {bot.user.id})")

# ---------------------- helpers ----------------------
async def normalize(s: str) -> str:
    return " ".join(s.lower().strip().split())

async def has_min_role(interaction: discord.Interaction) -> bool:
    role_id_str = await bot.get_setting("min_claim_role_id")
    if not role_id_str:
        return False
    role = interaction.guild.get_role(int(role_id_str))
    if not role:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    return any(r >= role for r in member.roles)

async def get_log_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    log_id = await bot.get_setting("log_channel_id")
    return guild.get_channel(int(log_id)) if log_id else None

async def ensure_seed_for_guild(guild_id: int):
    async with bot.db.execute("SELECT COUNT(*) FROM open_all_categories WHERE guild_id=?", (guild_id,)) as cur:
        count = (await cur.fetchone())[0]
    if count == 0:
        await bot.db.executemany(
            "INSERT INTO open_all_categories(guild_id, name) VALUES(?, ?)",
            [(guild_id, name) for name in sorted(OPEN_TO_ALL_SEED)]
        )
        await bot.db.commit()

async def compute_open_to_all(guild_id: int, category: Optional[str]) -> bool:
    if not category:
        return False
    await ensure_seed_for_guild(guild_id)
    n = await normalize(category)
    async with bot.db.execute("SELECT 1 FROM open_all_categories WHERE guild_id=? AND LOWER(name)=?", (guild_id, n)) as cur:
        return (await cur.fetchone()) is not None

# ---------------------- setup commands ----------------------
@bot.tree.command(description="Configure help (overview)")
@app_commands.default_permissions(manage_guild=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(title="Setup Commands", color=discord.Color.blurple())
    embed.add_field(name="/set-general #channel", value="Announcements channel (weekly + 2-day pings)", inline=False)
    embed.add_field(name="/set-log #channel", value="Log channel for warnings & job activity", inline=False)
    embed.add_field(name="/set-min-claim-role @role", value="Minimum role to claim role-gated jobs", inline=False)
    embed.add_field(name="/rotation add/remove/list", value="Manage weekly interview rotation", inline=False)
    embed.add_field(name="/interview", value="Announce current interview candidate now", inline=False)
    embed.add_field(name="/job_add", value="Create a job (with Category) + claim buttons", inline=False)
    embed.add_field(name="/openall add/remove/list", value="Manage categories anyone can claim", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(description="Set general announcements channel")
@app_commands.default_permissions(manage_guild=True)
async def set_general(interaction: discord.Interaction, channel: discord.TextChannel):
    await bot.set_setting("general_channel_id", str(channel.id))
    await interaction.response.send_message(f"General channel set to {channel.mention}", ephemeral=True)

@bot.tree.command(description="Set log channel")
@app_commands.default_permissions(manage_guild=True)
async def set_log(interaction: discord.Interaction, channel: discord.TextChannel):
    await bot.set_setting("log_channel_id", str(channel.id))
    await interaction.response.send_message(f"Log channel set to {channel.mention}", ephemeral=True)

@bot.tree.command(description="Set minimum role required to claim role-gated jobs")
@app_commands.default_permissions(manage_guild=True)
async def set_min_claim_role(interaction: discord.Interaction, role: discord.Role):
    await bot.set_setting("min_claim_role_id", str(role.id))
    await interaction.response.send_message(f"Minimum claim role set to {role.mention}", ephemeral=True)

# ---------------------- rotation ----------------------
rotation = app_commands.Group(name="rotation", description="Manage weekly interview rotation")
bot.tree.add_command(rotation)

@rotation.command(name="add", description="Add user to interview rotation (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def rotation_add(interaction: discord.Interaction, user: discord.Member):
    await bot.db.execute("INSERT INTO interview_rotation(guild_id, user_id) VALUES(?, ?)", (interaction.guild.id, user.id))
    await bot.db.commit()
    await interaction.response.send_message(f"Added {user.mention} to rotation.", ephemeral=True)

@rotation.command(name="remove", description="Remove user from interview rotation (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def rotation_remove(interaction: discord.Interaction, user: discord.Member):
    await bot.db.execute("DELETE FROM interview_rotation WHERE guild_id=? AND user_id=?", (interaction.guild.id, user.id))
    await bot.db.commit()
    await interaction.response.send_message(f"Removed {user.mention} from rotation.", ephemeral=True)

@rotation.command(name="list", description="List rotation users")
async def rotation_list(interaction: discord.Interaction):
    async with bot.db.execute("SELECT user_id FROM interview_rotation WHERE guild_id=? ORDER BY id", (interaction.guild.id,)) as cur:
        rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message("Rotation is empty.", ephemeral=True)
    mentions = []
    for (uid,) in rows:
        member = interaction.guild.get_member(uid)
        mentions.append(member.mention if member else f"<@{uid}>")
    await interaction.response.send_message("Rotation: " + ", ".join(mentions))

@bot.tree.command(description="Announce the current interview candidate now")
async def interview(interaction: discord.Interaction):
    general_id = await bot.get_setting("general_channel_id")
    if not general_id:
        return await interaction.response.send_message("General channel not set.", ephemeral=True)
    channel = interaction.guild.get_channel(int(general_id))
    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message("General channel invalid.", ephemeral=True)
    candidate = await bot._current_candidate(interaction.guild.id)
    if not candidate:
        return await interaction.response.send_message("No candidates in rotation.", ephemeral=True)
    await channel.send(f"📣 This week's interview: {candidate.mention}! (2-day reminders enabled)")
    await interaction.response.send_message("Announced.", ephemeral=True)

# ---------------------- open-to-all category management ----------------------
openall = app_commands.Group(name="openall", description="Manage open-to-all job categories")
bot.tree.add_command(openall)

@openall.command(name="add", description="Add an open-to-all category (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def openall_add(interaction: discord.Interaction, name: str):
    await ensure_seed_for_guild(interaction.guild.id)
    n = await normalize(name)
    async with bot.db.execute("SELECT 1 FROM open_all_categories WHERE guild_id=? AND LOWER(name)=?", (interaction.guild.id, n)) as cur:
        if await cur.fetchone():
            return await interaction.response.send_message("Category already exists.", ephemeral=True)
    await bot.db.execute("INSERT INTO open_all_categories(guild_id, name) VALUES(?, ?)", (interaction.guild.id, n))
    await bot.db.commit()
    await interaction.response.send_message(f"Added open-to-all category: **{n}**", ephemeral=True)

@openall.command(name="remove", description="Remove an open-to-all category (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def openall_remove(interaction: discord.Interaction, name: str):
    n = await normalize(name)
    await bot.db.execute("DELETE FROM open_all_categories WHERE guild_id=? AND LOWER(name)=?", (interaction.guild.id, n))
    await bot.db.commit()
    await interaction.response.send_message(f"Removed open-to-all category: **{n}**", ephemeral=True)

@openall.command(name="list", description="List open-to-all categories")
async def openall_list(interaction: discord.Interaction):
    await ensure_seed_for_guild(interaction.guild.id)
    async with bot.db.execute("SELECT name FROM open_all_categories WHERE guild_id=? ORDER BY name", (interaction.guild.id,)) as cur:
        rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message("No open-to-all categories.", ephemeral=True)
    names = ", ".join(name for (name,) in rows)
    await interaction.response.send_message(f"Open-to-all categories: {names}")

# ---------------------- jobs ----------------------
class JobBoardView(discord.ui.View):
    def __init__(self, job_id: int):
        super().__init__(timeout=None)
        self.job_id = job_id

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="job_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        async with bot.db.execute("SELECT status, claimed_by, open_to_all FROM jobs WHERE id=?", (self.job_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Job not found.", ephemeral=True)
        status, claimed_by, open_to_all = row
        if status == "closed":
            return await interaction.response.send_message("Job is closed.", ephemeral=True)
        if claimed_by:
            return await interaction.response.send_message("Already claimed.", ephemeral=True)
        if not open_to_all and not await has_min_role(interaction):
            return await interaction.response.send_message("You don't have permission to claim this job.", ephemeral=True)

        await bot.db.execute("UPDATE jobs SET claimed_by=?, status='claimed' WHERE id=?", (interaction.user.id, self.job_id))
        await bot.db.commit()
        await interaction.response.send_message(f"✅ {interaction.user.mention} claimed job #{self.job_id}.")
        log_ch = await get_log_channel(interaction.guild)
        if log_ch:
            await log_ch.send(f"📝 Job #{self.job_id} claimed by {interaction.user.mention}.")

    @discord.ui.button(label="Unclaim", style=discord.ButtonStyle.secondary, custom_id="job_unclaim")
    async def unclaim(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        async with bot.db.execute("SELECT status, claimed_by FROM jobs WHERE id=?", (self.job_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return await interaction.response.send_message("Job not found.", ephemeral=True)
        status, claimed_by = row
        if status == "closed":
            return await interaction.response.send_message("Job is closed.", ephemeral=True)
        if not claimed_by:
            return await interaction.response.send_message("Job is not claimed.", ephemeral=True)
        is_owner = int(claimed_by) == interaction.user.id
        is_manager = interaction.user.guild_permissions.manage_messages
        if not (is_owner or is_manager):
            return await interaction.response.send_message("Only the claimer or a moderator can unclaim.", ephemeral=True)

        await bot.db.execute("UPDATE jobs SET claimed_by=NULL, status='open' WHERE id=?", (self.job_id,))
        await bot.db.commit()
        await interaction.response.send_message(f"↩️ {interaction.user.mention} unclaimed job #{self.job_id}.")
        log_ch = await get_log_channel(interaction.guild)
        if log_ch:
            await log_ch.send(f"📤 Job #{self.job_id} unclaimed by {interaction.user.mention}.")

class JobModal(discord.ui.Modal, title="Create a Job"):
    title_input = discord.ui.TextInput(label="Title", placeholder="e.g., Write feature on local event", max_length=100)
    category_input = discord.ui.TextInput(label="Category", placeholder="e.g., Staff Birthdays", required=False, max_length=60)
    desc_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        cat = str(self.category_input) if self.category_input else None
        open_to_all = 1 if await compute_open_to_all(interaction.guild.id, cat) else 0
        await bot.db.execute(
            "INSERT INTO jobs(guild_id, title, description, category, open_to_all, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (interaction.guild.id, str(self.title_input), str(self.desc_input), cat, open_to_all, dt.datetime.utcnow().isoformat())
        )
        await bot.db.commit()
        async with bot.db.execute("SELECT last_insert_rowid()") as cur:
            job_id = (await cur.fetchone())[0]
        view = JobBoardView(job_id)
        badge = "🌐 Open to all" if open_to_all else "🔒 Role-gated"
        cat_txt = f"\n**Category:** {cat}" if cat else ""
        embed = discord.Embed(
            title=f"Job #{job_id}: {self.title_input}",
            description=(str(self.desc_input) or "No description") + cat_txt,
            color=discord.Color.green()
        )
        embed.set_footer(text=badge)
        await interaction.response.send_message(embed=embed, view=view)
        log_ch = await get_log_channel(interaction.guild)
        if log_ch:
            await log_ch.send(f"🆕 Job #{job_id} created by {interaction.user.mention}: **{self.title_input}** ({badge})")

@bot.tree.command(description="Create a job with interactive claim/unclaim buttons (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def job_add(interaction: discord.Interaction):
    await ensure_seed_for_guild(interaction.guild.id)
    await interaction.response.send_modal(JobModal())

@bot.tree.command(description="List recent jobs")
async def job_list(interaction: discord.Interaction, status: Optional[str] = None):
    q = "SELECT id, title, status, claimed_by, open_to_all, category FROM jobs WHERE guild_id=?"
    params: List = [interaction.guild.id]
    if status:
        q += " AND status=?"
        params.append(status)
    q += " ORDER BY id DESC LIMIT 20"
    async with bot.db.execute(q, params) as cur:
        rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message("No jobs found.", ephemeral=True)
    lines = []
    for jid, title, st, claimer, open_to_all, category in rows:
        badge = "🌐" if open_to_all else "🔒"
        claimer_txt = f" by <@{claimer}>" if claimer else ""
        cat_txt = f" [{category}]" if category else ""
        lines.append(f"`#{jid}` {badge} **{title}**{cat_txt} — {st}{claimer_txt}")
    await interaction.response.send_message("\n".join(lines))

@bot.tree.command(description="Close a job (Admin or claimer)")
async def job_close(interaction: discord.Interaction, job_id: int):
    async with bot.db.execute("SELECT status, claimed_by FROM jobs WHERE id=?", (job_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message("Job not found.", ephemeral=True)
    status, claimed_by = row
    is_owner = claimed_by and int(claimed_by) == interaction.user.id
    is_admin = interaction.user.guild_permissions.manage_guild
    if not (is_owner or is_admin):
        return await interaction.response.send_message("Only the claimer or an admin can close this job.", ephemeral=True)
    await bot.db.execute("UPDATE jobs SET status='closed' WHERE id=?", (job_id,))
    await bot.db.commit()
    await interaction.response.send_message(f"🔒 Job #{job_id} closed.")
    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(f"🔒 Job #{job_id} closed by {interaction.user.mention}.")

@bot.tree.command(description="Re-open a closed job (Admin)")
@app_commands.default_permissions(manage_guild=True)
async def job_open(interaction: discord.Interaction, job_id: int):
    async with bot.db.execute(
        "SELECT status FROM jobs WHERE id=? AND guild_id=?",
        (job_id, interaction.guild.id)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return await interaction.response.send_message("Job not found.", ephemeral=True)
    if row[0] != "closed":
        return await interaction.response.send_message("Only closed jobs can be reopened.", ephemeral=True)

    await bot.db.execute("UPDATE jobs SET status='open', claimed_by=NULL WHERE id=?", (job_id,))
    await bot.db.commit()
    await interaction.response.send_message(f"🔓 Job #{job_id} reopened.")

    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(f"🔓 Job #{job_id} reopened by {interaction.user.mention}.")
@bot.tree.command(description="Quick-create a job (no modal)")
@app_commands.describe(
    title="Job title",
    category="Optional category (affects open-to-all)",
    description="Optional description"
)
@app_commands.default_permissions(manage_guild=True)
async def job_post(
    interaction: discord.Interaction,
    title: str,
    category: Optional[str] = None,
    description: Optional[str] = None
):
    await ensure_seed_for_guild(interaction.guild.id)
    open_to_all = 1 if await compute_open_to_all(interaction.guild.id, category) else 0

    await bot.db.execute(
        "INSERT INTO jobs(guild_id, title, description, category, open_to_all, created_at) VALUES(?, ?, ?, ?, ?, ?)",
        (interaction.guild.id, title, description or "", category, open_to_all, dt.datetime.utcnow().isoformat())
    )
    await bot.db.commit()
    async with bot.db.execute("SELECT last_insert_rowid()") as cur:
        job_id = (await cur.fetchone())[0]

    view = JobBoardView(job_id)
    badge = "🌐 Open to all" if open_to_all else "🔒 Role-gated"
    cat_txt = f"\n**Category:** {category}" if category else ""
    embed = discord.Embed(
        title=f"Job #{job_id}: {title}",
        description=(description or "No description") + cat_txt,
        color=discord.Color.green()
    )
    embed.set_footer(text=badge)
    await interaction.response.send_message(embed=embed, view=view)

    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(f"🆕 Job #{job_id} created by {interaction.user.mention}: **{title}** ({badge})")
@bot.tree.command(description="Delete a job (Admin)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    job_id="The numeric ID shown in /job_list",
    reason="Optional reason to include in logs"
)
async def job_delete(interaction: discord.Interaction, job_id: int, reason: Optional[str] = None):
    # Fetch job details first (for a nice log message)
    async with bot.db.execute(
        "SELECT title, status, claimed_by, category FROM jobs WHERE id=? AND guild_id=?",
        (job_id, interaction.guild.id)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return await interaction.response.send_message("Job not found.", ephemeral=True)

    title, status, claimed_by, category = row

    # Delete the job
    await bot.db.execute("DELETE FROM jobs WHERE id=? AND guild_id=?", (job_id, interaction.guild.id))
    await bot.db.commit()

    # Tell the channel and log it
    await interaction.response.send_message(f"🗑️ Deleted job `#{job_id}`: **{title}**.")
    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        details = [f"status={status}"]
        if claimed_by:
            details.append(f"claimed_by=<@{claimed_by}>")
        if category:
            details.append(f"category={category}")
        details_str = ", ".join(details)
        rsn = f" Reason: {reason}" if reason else ""
        await log_ch.send(f"🗑️ Job `#{job_id}` (**{title}**) deleted by {interaction.user.mention}. {details_str}.{rsn}")


# ---------------------- warnings ----------------------
warns = app_commands.Group(name="warn", description="Manage warnings")
bot.tree.add_command(warns)

@warns.command(name="add", description="Add a warning to a user")
async def warn_add(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.manage_messages):
        return await interaction.response.send_message("You don't have permission to warn.", ephemeral=True)
    await bot.db.execute(
        "INSERT INTO warnings(guild_id, user_id, moderator_id, reason, created_at) VALUES(?, ?, ?, ?, ?)",
        (interaction.guild.id, user.id, interaction.user.id, reason, dt.datetime.utcnow().isoformat())
    )
    await bot.db.commit()
    await interaction.response.send_message(f"⚠️ Warned {user.mention}: {reason}")
    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(f"⚠️ {user.mention} warned by {interaction.user.mention}: {reason}")

@warns.command(name="remove", description="Remove the most recent warning from a user")
async def warn_remove(interaction: discord.Interaction, user: discord.Member):
    if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.manage_messages):
        return await interaction.response.send_message("You don't have permission to remove warnings.", ephemeral=True)
    async with bot.db.execute(
        "SELECT id FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
        (interaction.guild.id, user.id)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return await interaction.response.send_message("No warnings to remove.", ephemeral=True)
    await bot.db.execute("DELETE FROM warnings WHERE id=?", (row[0],))
    await bot.db.commit()
    await interaction.response.send_message(f"🧹 Removed latest warning for {user.mention}.")
    log_ch = await get_log_channel(interaction.guild)
    if log_ch:
        await log_ch.send(f"🧹 Removed a warning for {user.mention} (by {interaction.user.mention}).")

@warns.command(name="list", description="List a user's warnings")
async def warn_list(interaction: discord.Interaction, user: discord.Member):
    async with bot.db.execute(
        "SELECT id, reason, moderator_id, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 20",
        (interaction.guild.id, user.id)
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        return await interaction.response.send_message(f"{user.mention} has no warnings.")
    embed = discord.Embed(title=f"Warnings for {user}")
    for wid, reason, mod_id, created in rows:
        when = dt.datetime.fromisoformat(created)
        embed.add_field(
            name=f"ID {wid} — {when:%Y-%m-%d %H:%M} UTC",
            value=f"**By:** <@{mod_id}>\n**Reason:** {reason}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# ---------------------- startup (KEEP THIS AT THE BOTTOM) ----------------------
from pathlib import Path

async def main():
    env_path = Path(__file__).parent / ".env"
    load_dotenv(dotenv_path=env_path)

    token = os.getenv("DISCORD_TOKEN")
    print("[startup] cwd:", os.getcwd())
    print("[startup] .env exists:", env_path.exists())
    print("[startup] token loaded:", bool(token))

    if not token:
        print("Please set DISCORD_TOKEN in .env")
        return

    try:
        async with bot:
            await bot.start(token)
    except discord.LoginFailure as e:
        print("[startup] Login failed (bad token?):", e)
    except Exception as e:
        print("[startup] Unexpected error starting bot:", repr(e))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
