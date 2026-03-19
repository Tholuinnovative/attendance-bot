# 🚀 Deploy Attendance Bot to Railway (Step-by-Step)

---

## What You Need
- A free GitHub account → github.com
- A free Railway account → railway.app
- Your Telegram bot token (from @BotFather)

---

## STEP 1 — Upload files to GitHub

1. Go to **github.com** and sign in (or create a free account)
2. Click the **"+"** button (top right) → **"New repository"**
3. Name it: `attendance-bot`
4. Set it to **Private**
5. Click **"Create repository"**
6. On the next page, click **"uploading an existing file"**
7. Drag and drop these 4 files into the upload area:
   - `bot.py`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
8. Click **"Commit changes"**

✅ Your files are now on GitHub.

---

## STEP 2 — Deploy on Railway

1. Go to **railway.app**
2. Click **"Start a New Project"**
3. Click **"Deploy from GitHub repo"**
4. Sign in with your GitHub account when prompted
5. Select your `attendance-bot` repository
6. Railway will start setting up — wait about 30 seconds

---

## STEP 3 — Add Your Bot Token

This is the most important step!

1. In Railway, click on your project
2. Click the **"Variables"** tab
3. Click **"New Variable"**
4. Set:
   - **Name:** `TELEGRAM_BOT_TOKEN`
   - **Value:** paste your token from BotFather (e.g. `123456789:ABCdef...`)
5. Click **"Add"**
6. Railway will automatically restart your bot with the token

---

## STEP 4 — Check it's Running

1. Click the **"Deployments"** tab in Railway
2. Click on the latest deployment
3. Click **"View Logs"**
4. You should see:
   ```
   ✅ Database initialized.
   🤖 Attendance bot is running...
   ```

If you see that — **your bot is live 24/7!** 🎉

---

## STEP 5 — Test It

Go to your Telegram group and send:
```
/start
```
The bot should reply immediately.

---

## ⚠️ Common Issues

**Bot not responding?**
- Double-check the token in Railway Variables (no extra spaces)
- Make sure the bot is added to your group as Admin

**Deployment failed?**
- Go to Logs and look for red error text
- Most common cause: wrong token format

**"Application failed to respond"?**
- This is normal for bots — ignore it. Bots don't need a web URL.

---

## 💾 About the Database

Railway's free tier uses an **ephemeral filesystem** — this means the SQLite database (`attendance.db`) may reset if the bot restarts or redeploys.

**To keep data permanently**, after deploying add a free Railway PostgreSQL plugin:
- In your Railway project → click **"New"** → **"Database"** → **"PostgreSQL"**
- Then message me and I'll update the bot to use it.

For now, SQLite works fine for regular classes — just export your CSV after each session!
