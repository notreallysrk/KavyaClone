# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────
"""Clone management commands. Clones run as independent Telegram bot identities
while sharing FoxyMusic's per-chat queue and playback engine.
"""
from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

import config
from FoxyMusic import app
from FoxyMusic.core.client_context import remember_chat_client
from FoxyMusic.core.clone_manager import clone_manager
from config import BANNED_USERS


@app.on_message(filters.command(["clone"]) & ~BANNED_USERS)
async def clone_command(client, message: Message):
    # Clone bots must never create nested clones. Keep this check inside the
    # command handler as a server-side guard, not merely a hidden Help button.
    if getattr(client, "owner_id", None):
        main_username = getattr(app, "username", None)
        if not main_username:
            try:
                main_me = await app.get_me()
                main_username = main_me.username
            except Exception:
                main_username = None
        main_link = f"@{main_username}" if main_username else "the main bot"
        return await message.reply_text(
            "ʏᴏᴜ ᴄᴀɴ'ᴛ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ ɪɴ ᴄʟᴏɴᴇ ʙᴏᴛs. ❤️\n"
            f"ᴘʟᴇᴀsᴇ ᴜsᴇ ᴍᴀɪɴ ʙᴏᴛ {main_link} ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴄʟᴏɴᴇ."
        )

    args = message.command[1:]
    if not args:
        if not clone_manager.enabled:
            return await message.reply_text(
                "Clone system is not configured yet.\n\n"
                "Set MONGO_DB_URI and CLONE_ENCRYPTION_KEY, then restart the bot."
            )
        return await message.reply_text(
            "🤖 <b>Create your own KavyaMusic clone</b>\n\n"
            "1. Create a bot with @BotFather.\n"
            "2. Open this bot in private.\n"
            "3. Send <code>/clone BOT_TOKEN</code>.\n\n"
            "⚠️ A bot token is a password. Never send it in a group."
        )

    token = args[0].strip()
    if not message.from_user:
        return await message.reply_text("A user account is required to create a clone.")
    if message.chat.type != ChatType.PRIVATE:
        try:
            await message.delete()
        except Exception:
            pass
        return await message.reply_text(
            "🔒 Send /clone and your bot token in my private chat only. "
            "If you posted a token here, revoke it with @BotFather."
        )

    # Remove the token-bearing message before doing network/database work.
    try:
        await message.delete()
    except Exception:
        pass

    status = await message.reply_text("🔎 Validating token and starting your clone…")
    ok, detail, username = await clone_manager.create_clone(
        token, message.from_user.id if message.from_user else 0
    )
    if ok:
        await status.edit_text(
            f"✅ <b>{detail}</b>\n\n"
            "Add the clone bot to your group, promote it with the required "
            "permissions, then use <code>/play</code>.\n\n"
            "Its queue is shared by chat with the main bot and other clones."
        )
    else:
        await status.edit_text(f"❌ {detail}")


@app.on_message(filters.command(["clones"]) & ~BANNED_USERS)
async def clones_command(client, message: Message):
    if not message.from_user:
        return
    if not clone_manager.enabled:
        return await message.reply_text("Clone system is not configured.")
    try:
        records = await clone_manager.list_clones(message.from_user.id)
    except Exception:
        return await message.reply_text("Could not read clone records from MongoDB.")

    if not records:
        return await message.reply_text("You don't have any registered clones yet.")

    lines = [f"🤖 <b>Your registered clones: {len(records)}</b>"]
    for record in records[:50]:
        username = record.get("username") or "unknown"
        owner_id = record.get("owner_id", 0)
        if int(message.from_user.id) == int(config.OWNER_ID):
            lines.append(f"• @{username} — owner <code>{owner_id}</code>")
        else:
            lines.append(f"• @{username}")
    if len(records) > 50:
        lines.append(f"…and {len(records) - 50} more.")
    await message.reply_text("\n".join(lines))


@app.on_message(filters.command(["unclone"]) & ~BANNED_USERS)
async def unclone_command(client, message: Message):
    if not message.from_user:
        return
    args = message.command[1:]
    if not args:
        return await message.reply_text(
            "Usage: <code>/unclone BOT_TOKEN</code>\n"
            "The main owner can also use <code>/unclone @username</code>."
        )

    target = args[0].strip()
    if ":" in target and message.chat.type != ChatType.PRIVATE:
        try:
            await message.delete()
        except Exception:
            pass
        return await message.reply_text(
            "🔒 For security, remove a clone by token only in private chat."
        )
    if ":" in target:
        try:
            await message.delete()
        except Exception:
            pass

    status = await message.reply_text("🗑 Removing clone…")
    ok, detail = await clone_manager.remove_clone(target, message.from_user.id)
    await status.edit_text(("✅ " if ok else "❌ ") + detail)


@app.on_message(filters.command(["resetclones"]) & ~BANNED_USERS)
async def resetclones_command(client, message: Message):
    if not message.from_user or int(message.from_user.id) != int(config.OWNER_ID):
        return await message.reply_text("This command is only available to the main bot owner.")
    status = await message.reply_text("🔄 Restarting registered clone clients…")
    try:
        ok, failed = await clone_manager.restart_all()
        await status.edit_text(
            f"✅ Clone recovery complete.\nStarted/restarted: <b>{ok}</b>\nFailed: <b>{failed}</b>"
        )
    except Exception:
        await status.edit_text("❌ Could not restart the clone clients. Check the logs.")


# Track which bot last handled each chat. PyTgCalls stream-ended events don't
# carry the bot token, so the correct bot should post the next-track UI.
@app.on_message(filters.all, group=9999)
async def remember_main_message(client, message):
    try:
        if getattr(message, "chat", None):
            remember_chat_client(message.chat.id, client)
    except Exception:
        pass


@app.on_callback_query(filters.all, group=9999)
async def remember_main_callback(client, query):
    try:
        if query.message and query.message.chat:
            remember_chat_client(query.message.chat.id, client)
    except Exception:
        pass
