#!/usr/bin/env python3
"""
Telegram Attendance Bot
- Students mark attendance by sending /present
- Teacher opens/closes sessions with time limits
- SQLite storage
- CSV/Excel export
"""

import logging
import sqlite3
import csv
import io
import os
from datetime import datetime, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DB_PATH = "attendance.db"

# ─── Database Setup ────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS teachers (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            registered_at TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER,
            class_name TEXT,
            started_at TEXT,
            closes_at TEXT,
            is_open INTEGER DEFAULT 1,
            FOREIGN KEY (teacher_id) REFERENCES teachers(user_id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            student_id INTEGER,
            student_name TEXT,
            username TEXT,
            marked_at TEXT,
            UNIQUE(session_id, student_id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)
    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_PATH)


# ─── Helpers ───────────────────────────────────────────────────────────────────

def is_teacher(user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM teachers WHERE user_id=?", (user_id,)).fetchone()
        return row is not None


def get_active_session(teacher_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, class_name, started_at, closes_at FROM sessions "
            "WHERE teacher_id=? AND is_open=1 ORDER BY id DESC LIMIT 1",
            (teacher_id,)
        ).fetchone()
        if not row:
            return None
        session_id, class_name, started_at, closes_at = row
        # Auto-close if expired
        if closes_at:
            closes_dt = datetime.fromisoformat(closes_at)
            if datetime.utcnow() > closes_dt:
                conn.execute("UPDATE sessions SET is_open=0 WHERE id=?", (session_id,))
                conn.commit()
                return None
        return {"id": session_id, "class_name": class_name, "started_at": started_at, "closes_at": closes_at}


def get_any_active_session() -> Optional[dict]:
    """Find any currently open session (for students)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, teacher_id, class_name, started_at, closes_at FROM sessions WHERE is_open=1"
        ).fetchall()
        now = datetime.utcnow()
        for row in rows:
            session_id, teacher_id, class_name, started_at, closes_at = row
            if closes_at:
                closes_dt = datetime.fromisoformat(closes_at)
                if now > closes_dt:
                    conn.execute("UPDATE sessions SET is_open=0 WHERE id=?", (session_id,))
                    conn.commit()
                    continue
            return {"id": session_id, "teacher_id": teacher_id, "class_name": class_name,
                    "started_at": started_at, "closes_at": closes_at}
    return None


def format_time_remaining(closes_at: str) -> str:
    closes_dt = datetime.fromisoformat(closes_at)
    remaining = closes_dt - datetime.utcnow()
    if remaining.total_seconds() <= 0:
        return "Expired"
    mins, secs = divmod(int(remaining.total_seconds()), 60)
    return f"{mins}m {secs}s"


# ─── Teacher Commands ──────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"👋 Hello, {user.first_name}!\n\n"
        "📋 *Attendance Bot*\n\n"
        "*Teacher Commands:*\n"
        "• /register — Register as a teacher\n"
        "• /open <class> [minutes] — Open a session\n"
        "• /close — Close current session\n"
        "• /status — View current session\n"
        "• /export — Export attendance as CSV\n"
        "• /history — View past sessions\n\n"
        "*Student Commands:*\n"
        "• /present — Mark your attendance\n"
        "• /check — Check if session is open\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_teacher(user.id):
        await update.message.reply_text("✅ You're already registered as a teacher.")
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO teachers (user_id, username, full_name, registered_at) VALUES (?,?,?,?)",
            (user.id, user.username, user.full_name, datetime.utcnow().isoformat())
        )
        conn.commit()
    await update.message.reply_text(
        "✅ *You're now registered as a teacher!*\n\n"
        "Use /open <ClassName> [minutes] to start an attendance session.\n"
        "Example: `/open Math101 10` (10 minute window)",
        parse_mode="Markdown"
    )


async def open_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_teacher(user.id):
        await update.message.reply_text("❌ Only registered teachers can open sessions. Use /register first.")
        return

    existing = get_active_session(user.id)
    if existing:
        await update.message.reply_text(
            f"⚠️ You already have an open session: *{existing['class_name']}*\n"
            "Use /close to close it first.",
            parse_mode="Markdown"
        )
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/open <ClassName> [minutes]`\n"
            "Example: `/open Math101 15`\n"
            "Omit minutes for unlimited time.",
            parse_mode="Markdown"
        )
        return

    class_name = args[0]
    minutes = None
    closes_at = None
    closes_str = "No time limit"

    if len(args) >= 2:
        try:
            minutes = int(args[1])
            if minutes < 1:
                raise ValueError
            closes_at = (datetime.utcnow() + timedelta(minutes=minutes)).isoformat()
            closes_str = f"{minutes} minutes"
        except ValueError:
            await update.message.reply_text("⚠️ Invalid time. Use a whole number of minutes, e.g. `15`.", parse_mode="Markdown")
            return

    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (teacher_id, class_name, started_at, closes_at, is_open) VALUES (?,?,?,?,1)",
            (user.id, class_name, now, closes_at)
        )
        conn.commit()

    await update.message.reply_text(
        f"✅ *Session opened!*\n\n"
        f"📚 Class: *{class_name}*\n"
        f"⏱ Duration: {closes_str}\n\n"
        f"Students can now send /present to mark attendance.",
        parse_mode="Markdown"
    )


async def close_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_teacher(user.id):
        await update.message.reply_text("❌ Only teachers can close sessions.")
        return

    session = get_active_session(user.id)
    if not session:
        await update.message.reply_text("ℹ️ No active session to close.")
        return

    with get_conn() as conn:
        conn.execute("UPDATE sessions SET is_open=0 WHERE id=?", (session["id"],))
        count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE session_id=?", (session["id"],)
        ).fetchone()[0]
        conn.commit()

    await update.message.reply_text(
        f"🔒 *Session closed!*\n\n"
        f"📚 Class: *{session['class_name']}*\n"
        f"👥 Total present: *{count}*\n\n"
        f"Use /export to download the attendance list.",
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_teacher(user.id):
        await update.message.reply_text("❌ Only teachers can view session status.")
        return

    session = get_active_session(user.id)
    if not session:
        await update.message.reply_text("ℹ️ No active session. Use /open to start one.")
        return

    with get_conn() as conn:
        students = conn.execute(
            "SELECT student_name, username, marked_at FROM attendance WHERE session_id=? ORDER BY marked_at",
            (session["id"],)
        ).fetchall()

    time_info = ""
    if session["closes_at"]:
        time_info = f"⏳ Time remaining: *{format_time_remaining(session['closes_at'])}*\n"

    student_list = ""
    for i, (name, uname, marked_at) in enumerate(students, 1):
        t = datetime.fromisoformat(marked_at).strftime("%H:%M:%S")
        handle = f"@{uname}" if uname else ""
        student_list += f"{i}. {name} {handle} — {t}\n"

    if not student_list:
        student_list = "_No students yet_"

    await update.message.reply_text(
        f"📊 *Live Session Status*\n\n"
        f"📚 Class: *{session['class_name']}*\n"
        f"👥 Present: *{len(students)}*\n"
        f"{time_info}\n"
        f"*Attendance List:*\n{student_list}",
        parse_mode="Markdown"
    )


async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_teacher(user.id):
        await update.message.reply_text("❌ Only teachers can export attendance.")
        return

    args = context.args
    with get_conn() as conn:
        # If session ID given, export that; otherwise export latest closed or open
        if args:
            try:
                session_id = int(args[0])
            except ValueError:
                await update.message.reply_text("Usage: /export [session_id]")
                return
            session = conn.execute(
                "SELECT id, class_name, started_at, closes_at FROM sessions WHERE id=? AND teacher_id=?",
                (session_id, user.id)
            ).fetchone()
        else:
            session = conn.execute(
                "SELECT id, class_name, started_at, closes_at FROM sessions WHERE teacher_id=? ORDER BY id DESC LIMIT 1",
                (user.id,)
            ).fetchone()

        if not session:
            await update.message.reply_text("❌ No session found to export. Use /history to see session IDs.")
            return

        s_id, class_name, started_at, closes_at = session
        students = conn.execute(
            "SELECT student_name, username, student_id, marked_at FROM attendance WHERE session_id=? ORDER BY marked_at",
            (s_id,)
        ).fetchall()

    # Build CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "Full Name", "Username", "Telegram ID", "Marked At (UTC)"])
    for i, (name, uname, sid, marked_at) in enumerate(students, 1):
        writer.writerow([i, name, f"@{uname}" if uname else "", sid, marked_at])

    csv_bytes = output.getvalue().encode("utf-8")
    date_str = datetime.fromisoformat(started_at).strftime("%Y-%m-%d_%H%M")
    filename = f"attendance_{class_name}_{date_str}.csv"

    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"📎 *Attendance Export*\n📚 {class_name}\n👥 {len(students)} students present",
        parse_mode="Markdown"
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_teacher(user.id):
        await update.message.reply_text("❌ Only teachers can view history.")
        return

    with get_conn() as conn:
        sessions = conn.execute(
            "SELECT s.id, s.class_name, s.started_at, s.is_open, COUNT(a.id) as cnt "
            "FROM sessions s LEFT JOIN attendance a ON a.session_id=s.id "
            "WHERE s.teacher_id=? GROUP BY s.id ORDER BY s.id DESC LIMIT 10",
            (user.id,)
        ).fetchall()

    if not sessions:
        await update.message.reply_text("ℹ️ No sessions yet.")
        return

    lines = ["📜 *Recent Sessions (last 10):*\n"]
    for s_id, class_name, started_at, is_open, cnt in sessions:
        dt = datetime.fromisoformat(started_at).strftime("%b %d %H:%M")
        status_icon = "🟢" if is_open else "🔴"
        lines.append(f"{status_icon} *{class_name}* — {cnt} present — {dt} (ID: `{s_id}`)")

    lines.append("\nUse `/export <id>` to download a specific session.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ─── Student Commands ──────────────────────────────────────────────────────────

async def present(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = get_any_active_session()

    if not session:
        await update.message.reply_text(
            "❌ *No active session right now.*\n"
            "Wait for your teacher to open one, then send /present again.",
            parse_mode="Markdown"
        )
        return

    now = datetime.utcnow().isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO attendance (session_id, student_id, student_name, username, marked_at) VALUES (?,?,?,?,?)",
                (session["id"], user.id, user.full_name, user.username, now)
            )
            conn.commit()
        await update.message.reply_text(
            f"✅ *Attendance marked!*\n\n"
            f"📚 Class: *{session['class_name']}*\n"
            f"🕐 Time: {datetime.utcnow().strftime('%H:%M:%S')} UTC",
            parse_mode="Markdown"
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text(
            f"ℹ️ You've already marked attendance for *{session['class_name']}*.",
            parse_mode="Markdown"
        )


async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session = get_any_active_session()
    if not session:
        await update.message.reply_text("🔴 No attendance session is open right now.")
        return

    time_info = ""
    if session["closes_at"]:
        remaining = format_time_remaining(session["closes_at"])
        time_info = f"⏳ Closes in: *{remaining}*"
    else:
        time_info = "⏳ No time limit"

    await update.message.reply_text(
        f"🟢 *Session is open!*\n\n"
        f"📚 Class: *{session['class_name']}*\n"
        f"{time_info}\n\n"
        f"Send /present to mark your attendance.",
        parse_mode="Markdown"
    )


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Unknown command. Send /start to see available commands."
    )


# ─── Auto-close Job ───────────────────────────────────────────────────────────

async def auto_close_expired(context: ContextTypes.DEFAULT_TYPE):
    """Periodically close expired sessions and notify teacher."""
    with get_conn() as conn:
        now = datetime.utcnow().isoformat()
        expired = conn.execute(
            "SELECT id, teacher_id, class_name FROM sessions WHERE is_open=1 AND closes_at IS NOT NULL AND closes_at <= ?",
            (now,)
        ).fetchall()
        for s_id, teacher_id, class_name in expired:
            conn.execute("UPDATE sessions SET is_open=0 WHERE id=?", (s_id,))
            count = conn.execute("SELECT COUNT(*) FROM attendance WHERE session_id=?", (s_id,)).fetchone()[0]
            try:
                await context.bot.send_message(
                    chat_id=teacher_id,
                    text=f"⏰ *Session auto-closed!*\n\n📚 Class: *{class_name}*\n👥 Total present: *{count}*\n\nUse /export to download the list.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning(f"Could not notify teacher {teacher_id}: {e}")
        conn.commit()


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN environment variable not set.")
        print("   Set it with: export TELEGRAM_BOT_TOKEN='your_token_here'")
        return

    init_db()
    print("✅ Database initialized.")

    app = Application.builder().token(token).build()

    # Teacher commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("open", open_session))
    app.add_handler(CommandHandler("close", close_session))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(CommandHandler("history", history))

    # Student commands
    app.add_handler(CommandHandler("present", present))
    app.add_handler(CommandHandler("check", check))

    # Fallback
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # Auto-close job every 30 seconds
    app.job_queue.run_repeating(auto_close_expired, interval=30, first=10)

    print("🤖 Attendance bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
