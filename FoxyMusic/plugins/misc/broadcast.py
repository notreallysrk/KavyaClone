# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────

import asyncio
import re

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter
from pyrogram.errors import FloodWait

import config
from FoxyMusic import app, LOGGER
from FoxyMusic.core.client_context import get_client as get_current_client
from FoxyMusic.core.clone_manager import clone_manager
from FoxyMusic.misc import SUDOERS
from FoxyMusic.utils.database import (
    get_active_chats,
    get_authuser_names,
    get_served_chats,
    get_served_users,
    get_client as get_assistant_client,
)
from FoxyMusic.utils.decorators.language import language
from FoxyMusic.utils.formatters import alpha_to_int
from config import adminlist

IS_BROADCASTING = False
BROADCAST_FLAGS = (
    "-pin", "-pinloud", "-nobot", "-user", "-assistant", "-noforward"
)


def _parse_broadcast_args(message):
    """Extract broadcast text and switches without changing the message body."""
    raw = ""
    if message.text:
        parts = message.text.split(None, 1)
        if len(parts) > 1:
            raw = parts[1]
    flags = set()
    for flag in BROADCAST_FLAGS:
        if re.search(rf"(?<!\S){re.escape(flag)}(?!\S)", raw):
            flags.add(flag)
            raw = re.sub(rf"(?<!\S){re.escape(flag)}(?!\S)", " ", raw)
    return re.sub(r"\s+", " ", raw).strip(), flags


async def _retry_floodwait(send_callable):
    while True:
        try:
            return await send_callable()
        except FloodWait as exc:
            wait_time = int(getattr(exc, "value", None) or getattr(exc, "x", 1))
            await asyncio.sleep(max(1, wait_time))


async def _send_main_target(client, chat_id, source, text):
    if source is not None:
        return await _retry_floodwait(
            lambda: client.copy_message(
                chat_id=chat_id,
                from_chat_id=source.chat.id,
                message_id=source.id,
                reply_markup=source.reply_markup,
            )
        )
    return await _retry_floodwait(
        lambda: client.send_message(chat_id=chat_id, text=text)
    )


async def _prepare_clone_payload(source, text):
    """Prepare a message once so it can be re-sent by different bot tokens."""
    if source is None:
        return {"kind": "text", "text": text}
    if source.text:
        return {
            "kind": "text",
            "text": source.text,
            "entities": getattr(source, "entities", None),
            "reply_markup": source.reply_markup,
        }

    media_fields = (
        "photo", "video", "animation", "audio", "document", "voice",
        "video_note", "sticker",
    )
    for field in media_fields:
        if getattr(source, field, None):
            downloaded = await source.download(in_memory=True)
            if downloaded is None:
                raise RuntimeError("Telegram could not download the replied media.")
            return {
                "kind": "media",
                "field": field,
                "file": downloaded,
                "caption": getattr(source, "caption", None),
                "caption_entities": getattr(source, "caption_entities", None),
                "reply_markup": source.reply_markup,
            }

    if getattr(source, "contact", None):
        contact = source.contact
        return {"kind": "contact", "contact": contact}
    if getattr(source, "location", None):
        return {"kind": "location", "location": source.location}
    if getattr(source, "venue", None):
        return {"kind": "venue", "venue": source.venue}
    if source.caption:
        return {
            "kind": "text",
            "text": source.caption,
            "entities": getattr(source, "caption_entities", None),
            "reply_markup": source.reply_markup,
        }
    raise RuntimeError(
        "This replied message type cannot be copied to clone bots. "
        "Please use text or a photo/video/document/audio message."
    )


async def _send_clone_payload(client, chat_id, payload):
    kind = payload["kind"]
    if kind == "text":
        kwargs = {
            "chat_id": chat_id,
            "text": payload["text"],
            "reply_markup": payload.get("reply_markup"),
            "parse_mode": None,
        }
        if payload.get("entities"):
            kwargs["entities"] = payload["entities"]
        return await _retry_floodwait(lambda: client.send_message(**kwargs))

    if kind == "media":
        field = payload["field"]
        media_file = payload["file"]
        try:
            media_file.seek(0)
        except Exception:
            pass
        kwargs = {"chat_id": chat_id, field: media_file}
        if payload.get("caption") and field not in ("video_note", "sticker"):
            kwargs["caption"] = payload["caption"]
            kwargs["parse_mode"] = None
            if payload.get("caption_entities"):
                kwargs["caption_entities"] = payload["caption_entities"]
        if payload.get("reply_markup") and field not in ("video_note", "sticker"):
            kwargs["reply_markup"] = payload["reply_markup"]
        method = getattr(client, f"send_{field}")
        return await _retry_floodwait(lambda: method(**kwargs))

    if kind == "contact":
        item = payload["contact"]
        return await _retry_floodwait(lambda: client.send_contact(
            chat_id, item.phone_number, item.first_name,
            last_name=item.last_name, vcard=item.vcard,
        ))
    if kind == "location":
        item = payload["location"]
        return await _retry_floodwait(lambda: client.send_location(
            chat_id, item.latitude, item.longitude,
        ))
    if kind == "venue":
        item = payload["venue"]
        return await _retry_floodwait(lambda: client.send_venue(
            chat_id, item.location.latitude, item.location.longitude,
            item.title, item.address,
        ))
    raise RuntimeError("Unsupported clone broadcast payload.")


def _pin_mode(flags):
    if "-pinloud" in flags:
        return False
    if "-pin" in flags:
        return True
    return None


async def _pin_if_requested(sent_message, flags):
    pin_mode = _pin_mode(flags)
    if pin_mode is None or sent_message is None:
        return False
    try:
        await sent_message.pin(disable_notification=pin_mode)
        return True
    except Exception:
        return False


@app.on_message(filters.command("broadcast") & SUDOERS)
@language
async def broadcast_message(client, message, _):
    global IS_BROADCASTING
    if IS_BROADCASTING:
        return await message.reply_text("A broadcast is already running. Please wait.")

    source = message.reply_to_message
    query, flags = _parse_broadcast_args(message)
    if source is None and not query:
        return await message.reply_text(_["broad_2"])

    broadcast_client = get_current_client() or app
    IS_BROADCASTING = True
    status = None
    sent = failed = pins = user_sent = user_failed = 0
    assistant_report = []

    try:
        status = await message.reply_text(_["broad_1"])
        if "-nobot" not in flags:
            chats = await get_served_chats()
            for chat in chats:
                chat_id = int(chat["chat_id"])
                try:
                    delivered = await _send_main_target(
                        broadcast_client, chat_id, source, query
                    )
                    sent += 1
                    pins += int(await _pin_if_requested(delivered, flags))
                except Exception as exc:
                    failed += 1
                    LOGGER(__name__).warning(
                        "Broadcast delivery failed for chat %s: %s",
                        chat_id, type(exc).__name__,
                    )
                await asyncio.sleep(0.05)

        if "-user" in flags:
            users = await get_served_users()
            for user in users:
                user_id = int(user["user_id"])
                try:
                    await _send_main_target(
                        broadcast_client, user_id, source, query
                    )
                    user_sent += 1
                except Exception as exc:
                    user_failed += 1
                    LOGGER(__name__).debug(
                        "User broadcast failed for %s: %s",
                        user_id, type(exc).__name__,
                    )
                await asyncio.sleep(0.05)

        if "-assistant" in flags:
            from FoxyMusic.core.userbot import assistants

            for number in assistants:
                assistant_client = await get_assistant_client(number)
                if assistant_client is None:
                    assistant_report.append(f"Assistant {number}: unavailable")
                    continue
                assistant_sent = 0
                async for dialog in assistant_client.get_dialogs():
                    try:
                        if source is not None:
                            await _retry_floodwait(lambda: assistant_client.copy_message(
                                chat_id=dialog.chat.id,
                                from_chat_id=source.chat.id,
                                message_id=source.id,
                                reply_markup=source.reply_markup,
                            ))
                        else:
                            await _retry_floodwait(lambda: assistant_client.send_message(
                                dialog.chat.id, query
                            ))
                        assistant_sent += 1
                    except Exception:
                        continue
                    await asyncio.sleep(1)
                assistant_report.append(
                    f"Assistant {number}: {assistant_sent} chats"
                )

        report = (
            "<b>Broadcast completed</b>\n\n"
            f"• Groups/channels delivered: <code>{sent}</code>\n"
            f"• Group/channel failures: <code>{failed}</code>\n"
            f"• Users delivered: <code>{user_sent}</code>\n"
            f"• User failures: <code>{user_failed}</code>\n"
            f"• Messages pinned: <code>{pins}</code>"
        )
        if assistant_report:
            report += "\n\n" + "\n".join(assistant_report)
        await status.edit_text(report)
    except Exception as exc:
        LOGGER(__name__).exception("Broadcast stopped unexpectedly")
        try:
            if status is not None:
                await status.edit_text(
                    f"Broadcast stopped due to an error: <code>{type(exc).__name__}</code>"
                )
        except Exception:
            pass
    finally:
        IS_BROADCASTING = False


@app.on_message(filters.command("cbroadcast") & filters.user(config.OWNER_ID))
async def clone_broadcast_message(client, message):
    """Broadcast from every active clone bot. Main owner only."""
    global IS_BROADCASTING
    if IS_BROADCASTING:
        return await message.reply_text("A broadcast is already running. Please wait.")

    source = message.reply_to_message
    query, flags = _parse_broadcast_args(message)
    if source is None and not query:
        return await message.reply_text(
            "Reply to a message or use <code>/cbroadcast your message</code>."
        )

    clones = [
        clone for clone in clone_manager.clients.values()
        if getattr(clone, "is_connected", False)
    ]
    if not clones:
        return await message.reply_text("No active clone bots are running right now.")

    try:
        payload = await _prepare_clone_payload(source, query)
    except Exception as exc:
        return await message.reply_text(
            f"Could not prepare the broadcast message: <code>{type(exc).__name__}</code>"
        )

    IS_BROADCASTING = True
    status = None
    total_sent = total_failed = total_pins = 0
    per_clone = []

    try:
        status = await message.reply_text(
            f"Starting clone broadcast on <code>{len(clones)}</code> active clone bots..."
        )
        for clone in clones:
            clone_sent = clone_failed = 0
            bot_id = int(getattr(clone, "id", 0) or (await clone.get_me()).id)
            # Include old unscoped records for backwards compatibility. The
            # previous database stored all bots' chats together; each clone
            # will deliver only where Telegram still allows it.
            clone_chats = await get_served_chats(
                bot_id=bot_id, include_legacy=True
            )
            for chat in clone_chats:
                chat_id = int(chat["chat_id"])
                try:
                    delivered = await _send_clone_payload(clone, chat_id, payload)
                    clone_sent += 1
                    total_pins += int(await _pin_if_requested(delivered, flags))
                except Exception as exc:
                    clone_failed += 1
                    LOGGER(__name__).debug(
                        "Clone broadcast failed for @%s in %s: %s",
                        getattr(clone, "username", "unknown"),
                        chat_id, type(exc).__name__,
                    )
                await asyncio.sleep(0.05)

            if "-user" in flags:
                clone_users = await get_served_users(
                    bot_id=bot_id, include_legacy=True
                )
                for user in clone_users:
                    user_id = int(user["user_id"])
                    try:
                        await _send_clone_payload(clone, user_id, payload)
                        clone_sent += 1
                    except Exception as exc:
                        clone_failed += 1
                        LOGGER(__name__).debug(
                            "Clone user broadcast failed for @%s to %s: %s",
                            getattr(clone, "username", "unknown"),
                            user_id, type(exc).__name__,
                        )
                    await asyncio.sleep(0.05)

            total_sent += clone_sent
            total_failed += clone_failed
            username = getattr(clone, "username", None) or str(bot_id)
            per_clone.append(
                f"• @{username}: <code>{clone_sent}</code> sent, "
                f"<code>{clone_failed}</code> failed"
            )

        report = (
            "<b>Clone broadcast completed</b>\n\n"
            f"• Active clone bots: <code>{len(clones)}</code>\n"
            f"• Total delivered: <code>{total_sent}</code>\n"
            f"• Total failed: <code>{total_failed}</code>\n"
            f"• Messages pinned: <code>{total_pins}</code>\n\n"
            + "\n".join(per_clone)
        )
        await status.edit_text(report)
    except Exception as exc:
        LOGGER(__name__).exception("Clone broadcast stopped unexpectedly")
        try:
            if status is not None:
                await status.edit_text(
                    f"Clone broadcast stopped due to an error: <code>{type(exc).__name__}</code>"
                )
        except Exception:
            pass
    finally:
        IS_BROADCASTING = False


async def auto_clean():
    while not await asyncio.sleep(10):
        try:
            served_chats = await get_active_chats()
            for chat_id in served_chats:
                if chat_id not in adminlist:
                    adminlist[chat_id] = []
                    async for user in get_current_client().get_chat_members(
                        chat_id, filter=ChatMembersFilter.ADMINISTRATORS
                    ):
                        if user.privileges.can_manage_video_chats:
                            adminlist[chat_id].append(user.user.id)
                    authusers = await get_authuser_names(chat_id)
                    for user in authusers:
                        user_id = await alpha_to_int(user)
                        adminlist[chat_id].append(user_id)
        except Exception:
            continue


asyncio.create_task(auto_clean())
