# ─────「 𝐅ᴏxʏ 」─────
# Group add/remove logger for the main bot.

import html
import os

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from FoxyMusic import app
from FoxyMusic.utils.database import add_served_chat
from config import LOGGER_ID


_LOG_IMAGE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../assets/upic.png")
)


def _safe(value, fallback="PRIVATE"):
    return html.escape(str(value)) if value not in (None, "") else fallback


def _actor_text(user):
    """Return a safe actor label, including anonymous-admin fallback."""
    if not user:
        return "<b>ANONYMOUS USER</b>"
    return getattr(user, "mention", None) or html.escape(user.first_name or "Unknown User")


async def _chat_link(client: Client, chat) -> str | None:
    """Get a public link or create a private invite link when permitted."""
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}"
    try:
        invite = await client.create_chat_invite_link(chat.id)
        return invite.invite_link
    except Exception:
        return None


async def _send_and_pin(client: Client, caption: str, keyboard):
    if not LOGGER_ID:
        return

    if os.path.isfile(_LOG_IMAGE):
        sent = await client.send_photo(
            chat_id=LOGGER_ID,
            photo=_LOG_IMAGE,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    else:
        sent = await client.send_message(
            chat_id=LOGGER_ID,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    # Pin each join/leave event in the logger group, without notifying everyone.
    try:
        await client.pin_chat_message(
            chat_id=LOGGER_ID,
            message_id=sent.id,
            disable_notification=True,
        )
    except Exception:
        # Logging should still succeed if the bot lacks pin permission.
        pass


@app.on_message(filters.new_chat_members)
async def on_new_chat_members(client: Client, message: Message):
    # This logger is specifically for the primary bot, not its clones.
    if getattr(client, "id", None) != getattr(app, "id", None):
        return
    if not LOGGER_ID or not message.new_chat_members:
        return
    if not any(member.id == client.id for member in message.new_chat_members):
        return

    chat = message.chat
    actor = _actor_text(message.from_user)
    title = _safe(chat.title, "Untitled Group")
    username = f"@{_safe(chat.username)}" if chat.username else "PRIVATE GROUP"
    chat_id = chat.id

    try:
        member_count = await client.get_chat_members_count(chat_id)
    except Exception:
        member_count = "UNKNOWN"

    link = await _chat_link(client, chat)
    link_line = (
        f"📬 <b>CHAT LINK :</b> <a href=\"{link}\">CLICK HERE</a>"
        if link
        else "📬 <b>CHAT LINK :</b> NOT FOUND"
    )

    caption = (
        "📝 <b>MUSIC BOT ADDED IN A NEW GROUP</b>\n\n"
        f"📌 <b>CHAT NAME :</b> {title}\n"
        f"🍂 <b>CHAT ID :</b> <code>{chat_id}</code>\n"
        f"🔐 <b>CHAT USERNAME :</b> {username}\n"
        f"{link_line}\n"
        f"📈 <b>GROUP MEMBERS :</b> {member_count}\n"
        f"🤔 <b>ADDED BY :</b> {actor}"
    )

    keyboard = (
        InlineKeyboardMarkup([[InlineKeyboardButton("SEE GROUP 👀", url=link)]])
        if link else None
    )

    await add_served_chat(chat_id)
    await _send_and_pin(client, caption, keyboard)


@app.on_message(filters.left_chat_member)
async def on_left_chat_member(client: Client, message: Message):
    # Only log when the primary bot itself is removed from a group.
    if getattr(client, "id", None) != getattr(app, "id", None):
        return
    if not LOGGER_ID or not message.left_chat_member:
        return
    if message.left_chat_member.id != client.id:
        return

    chat = message.chat
    actor = _actor_text(message.from_user)
    title = _safe(chat.title, "Untitled Group")
    chat_id = chat.id
    bot = await client.get_me()
    bot_username = bot.username
    add_url = f"https://t.me/{bot_username}?startgroup=true" if bot_username else None

    caption = (
        "✦ <b><u>#LEFT_GROUP</u></b>\n\n"
        f"🏷️ <b>CHAT TITLE :</b> {title}\n"
        f"🆔 <b>CHAT ID :</b> <code>{chat_id}</code>\n"
        f"👤 <b>REMOVED BY :</b> {actor}\n\n"
        f"🤖 <b>BOT :</b> @{_safe(bot_username, 'UNKNOWN')}"
    )

    keyboard = (
        InlineKeyboardMarkup(
            [[InlineKeyboardButton("➕ ADD ME AGAIN IN GROUPS ➕", url=add_url)]]
        )
        if add_url else None
    )

    await _send_and_pin(client, caption, keyboard)
