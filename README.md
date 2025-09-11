# Journalist-Bot
A bot to help Journalist with duties.
# Journalist Bot

A custom Discord bot for managing journalist-related tasks in a server.

## ✨ Features
- ⚠️ **Warnings**
  - `/warn add @user <reason>` — add a warning
  - `/warn remove @user` — remove latest warning
  - `/warn list @user` — view warnings
- 📰 **Jobs**
  - `/job_add` — create jobs with claim/unclaim buttons
  - `/job_list` — list recent jobs
  - `/job_close <id>` — close a job
  - Jobs can be **open-to-all** (anyone can claim) or **role-gated**
- 🎤 **Interviews**
  - Weekly interview rotation announcements
  - Auto pings every 2 days
  - `/rotation add/remove/list` — manage rotation
  - `/interview` — announce current candidate
- 📜 **Logging**
  - All job claims/unclaims and warnings are logged to a configured channel
- 🛠️ **Config Commands**
  - `/set-general #channel` — set announcements channel
  - `/set-log #channel` — set log channel
  - `/set-min-claim-role @role` — set minimum role to claim jobs
  - `/openall add/remove/list` — manage categories anyone can claim

## 🚀 Getting Started
### Prerequisites
- Python 3.10+
- [discord.py 2.x](https://github.com/Rapptz/discord.py)
- `aiosqlite` and `python-dotenv`

### Installation
```bash
git clone https://github.com/<your-username>/journalist-bot.git
cd journalist-bot
pip install -r requirements.txt
# Journalist Bot

A custom Discord bot for managing journalist-related tasks in a server.

## ✨ Features
- ⚠️ **Warnings**
  - `/warn add @user <reason>` — add a warning
  - `/warn remove @user` — remove latest warning
  - `/warn list @user` — view warnings
- 📰 **Jobs**
  - `/job_add` — create jobs with claim/unclaim buttons
  - `/job_list` — list recent jobs
  - `/job_close <id>` — close a job
  - Jobs can be **open-to-all** (anyone can claim) or **role-gated**
- 🎤 **Interviews**
  - Weekly interview rotation announcements
  - Auto pings every 2 days
  - `/rotation add/remove/list` — manage rotation
  - `/interview` — announce current candidate
- 📜 **Logging**
  - All job claims/unclaims and warnings are logged to a configured channel
- 🛠️ **Config Commands**
  - `/set-general #channel` — set announcements channel
  - `/set-log #channel` — set log channel
  - `/set-min-claim-role @role` — set minimum role to claim jobs
  - `/openall add/remove/list` — manage categories anyone can claim

## 🚀 Getting Started
### Prerequisites
- Python 3.10+
- [discord.py 2.x](https://github.com/Rapptz/discord.py)
- `aiosqlite` and `python-dotenv`

### Installation
```bash
git clone https://github.com/<your-username>/journalist-bot.git
cd journalist-bot
pip install -r requirements.txt
