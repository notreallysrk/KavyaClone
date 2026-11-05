# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────
"""Runtime clone manager for KustMusic-style token-based bot clones.

Clones are Pyrogram/Kurigram-compatible clients. They reuse the existing
plugin handlers and the shared music/queue state, while context-aware routing
makes Telegram API calls use the clone that received the update.

Unlike KustMusic's Bot API webhook transport, Pyrogram clients receive updates
through their own MTProto client connection. No webhook URL is needed here.
"""
import asyncio
import copy
import hashlib
import inspect
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from pyrogram import Client
from pyrogram.enums import ParseMode

import config
from FoxyMusic import app, LOGGER
from FoxyMusic.core.client_context import client_context, forget_client

TOKEN_RE = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{25,100}$")
MAX_CLONES_PER_USER = 5

# Commands that should only be handled by the primary bot. Music, settings,
# playback, help, language, and normal group commands remain available.
CLONE_BLOCKED_COMMANDS = {
    "unclone", "clones", "resetclones", "autoend", "autoleave", "stats",
    "broadcast", "bstatus", "bcancel", "prime", "live",
    "restart", "reboot", "reload", "update", "maintenance",
    "addsudo", "delsudo", "rmsudo", "sudolist", "listsudo", "sudoers",
    "gban", "globalban", "ungban", "gbannedusers", "gbanlist",
    "block", "unblock", "blocked", "blockedusers", "blusers",
    "blchat", "blacklistchat", "whitelistchat", "unblacklistchat",
    "unblchat", "blchats", "blacklistedchats", "logger",
    "getlog", "getlogs", "gitpull", "logs", "log", "disk", "dev",
}


def token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_cipher():
    key = getattr(config, "CLONE_ENCRYPTION_KEY", None)
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        LOGGER(__name__).error(
            "CLONE_ENCRYPTION_KEY is invalid; clone management is disabled "
            "(generate a Fernet key and set it as an environment variable)."
        )
        return None


def _chat_id_from_update(update):
    chat = getattr(update, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    message = getattr(update, "message", None)
    if message is None:
        message = getattr(update, "edited_message", None)
    if message is None:
        message = getattr(update, "channel_post", None)
    if message is not None:
        chat = getattr(message, "chat", None)
        return getattr(chat, "id", None) if chat else None
    return None


def _command_from_update(update):
    message = update if hasattr(update, "text") and hasattr(update, "chat") else None
    if message is None:
        message = getattr(update, "message", None)
    if message is None:
        message = getattr(update, "edited_message", None)
    if message is None:
        return None
    text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    if not text.startswith("/"):
        return None
    command = text.split(None, 1)[0][1:].split("@", 1)[0].lower()
    return command or None


class CloneManager:
    def __init__(self):
        self.collection = None
        self.clients = {}  # token fingerprint -> running Pyrogram Client
        self._lock = asyncio.Lock()
        self._cipher = _token_cipher()

    @property
    def enabled(self):
        return self._cipher is not None and bool(config.MONGO_DB_URI)

    def _encrypt(self, token):
        if self._cipher is None:
            raise RuntimeError("Clone encryption is not configured.")
        return self._cipher.encrypt(token.encode("utf-8")).decode("ascii")

    def _decrypt(self, value):
        if self._cipher is None:
            raise RuntimeError("Clone encryption is not configured.")
        return self._cipher.decrypt(value.encode("ascii")).decode("utf-8")

    def _ensure_collection(self):
        if self.collection is None:
            from FoxyMusic.core.mongo import mongodb
            self.collection = mongodb.clone_bots
        return self.collection

    def _wrap_handler(self, callback, clone_client):
        async def routed_callback(client, update, *args, **kwargs):
            chat_id = _chat_id_from_update(update)
            command = _command_from_update(update)
            if command in CLONE_BLOCKED_COMMANDS:
                return None
            with client_context(clone_client, chat_id):
                result = callback(client, update, *args, **kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result
        routed_callback.__name__ = getattr(callback, "__name__", "clone_handler")
        routed_callback.__doc__ = getattr(callback, "__doc__", None)
        return routed_callback

    def _attach_handlers(self, clone_client):
        """Copy registered handlers, preserving their filters and group order."""
        groups = getattr(getattr(app, "dispatcher", None), "groups", {})
        attached = 0
        for group, handlers in list(groups.items()):
            for original in list(handlers):
                callback = getattr(original, "callback", None)
                if callback is None:
                    continue
                callback_module = getattr(callback, "__module__", "")
                # Do not expose operational/owner-only modules through user clones.
                if callback_module.startswith("FoxyMusic.plugins.sudo"):
                    continue
                if callback_module in {
                    "FoxyMusic.plugins.misc.broadcast",
                    "FoxyMusic.plugins.tools.dev",
                    "FoxyMusic.plugins.tools.disk",
                    "FoxyMusic.plugins.tools.stats",
                }:
                    continue
                # The reload module also owns the generic `close` callback
                # used by music/help panels. Keep only that callback in clones;
                # operational reload/admin-cache commands stay main-bot-only.
                if callback_module == "FoxyMusic.plugins.tools.reload":
                    if getattr(callback, "__name__", "") != "close_menu":
                        continue
                cloned_handler = copy.copy(original)
                cloned_handler.callback = self._wrap_handler(callback, clone_client)
                clone_client.add_handler(cloned_handler, group=group)
                attached += 1
        if attached == 0:
            raise RuntimeError(
                "No handlers were available to copy. Clone startup must run "
                "after all KavyaMusic plugins have loaded."
            )
        return attached

    async def _start_client(self, token, owner_id=None):
        fingerprint = token_fingerprint(token)
        current = self.clients.get(fingerprint)
        if current is not None and getattr(current, "is_connected", False):
            if owner_id is not None:
                current.owner_id = int(owner_id)
            return current

        client = Client(
            name=f"FoxyClone_{fingerprint[:16]}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=token,
            in_memory=True,
            parse_mode=ParseMode.HTML,
            max_concurrent_transmissions=7,
        )
        # The start panel must identify the person who owns this clone, not
        # the owner configured for the primary bot.
        client.owner_id = int(owner_id if owner_id is not None else config.OWNER_ID)
        try:
            self._attach_handlers(client)
            await client.start()
            me = await client.get_me()
            if not me or not getattr(me, "is_bot", True):
                raise RuntimeError("Telegram did not return a valid bot account.")
            client.id = me.id
            client.name = (me.first_name or "") + (
                f" {me.last_name}" if me.last_name else ""
            )
            client.username = me.username
            client.mention = me.mention
            self.clients[fingerprint] = client
            LOGGER(__name__).info(
                "Clone client started: @%s (id=%s)", me.username, me.id
            )
            return client
        except Exception:
            try:
                if getattr(client, "is_connected", False):
                    await client.stop()
            except Exception:
                pass
            raise

    async def create_clone(self, token, owner_id):
        token = (token or "").strip()
        if not self.enabled:
            return False, (
                "Clone system is disabled. Configure MONGO_DB_URI and a valid "
                "CLONE_ENCRYPTION_KEY first."
            ), None
        if not TOKEN_RE.fullmatch(token):
            return False, "That does not look like a valid Telegram bot token.", None
        if token == config.BOT_TOKEN:
            return False, "That token belongs to the main bot.", None

        async with self._lock:
            collection = self._ensure_collection()
            fingerprint = token_fingerprint(token)
            try:
                existing = await collection.find_one({"_id": fingerprint})
            except Exception:
                LOGGER(__name__).exception("Clone database lookup failed")
                return False, "Database error while checking existing clones.", None

            if existing and int(existing.get("owner_id", 0)) not in (
                int(owner_id), int(config.OWNER_ID)
            ):
                return False, "That bot is already registered by another owner.", None

            if not existing and int(owner_id) != int(config.OWNER_ID):
                try:
                    count = await collection.count_documents({"owner_id": int(owner_id)})
                except Exception:
                    LOGGER(__name__).exception("Could not enforce clone quota")
                    return False, "Could not verify your clone limit; please retry.", None
                if count >= MAX_CLONES_PER_USER:
                    return False, f"You have reached the limit of {MAX_CLONES_PER_USER} clones.", None

            if existing and fingerprint in self.clients:
                client = self.clients[fingerprint]
                return True, f"@{client.username} is already running.", client.username

            try:
                client = await self._start_client(token, owner_id=owner_id)
            except Exception as exc:
                LOGGER(__name__).warning(
                    "Clone startup failed for fingerprint %s: %s",
                    fingerprint[:12], type(exc).__name__,
                )
                return False, (
                    "Telegram rejected this token or the clone could not start. "
                    "Check the token and try again."
                ), None

            try:
                await collection.update_one(
                    {"_id": fingerprint},
                    {
                        "$set": {
                            "token_encrypted": self._encrypt(token),
                            "bot_id": int(client.id),
                            "username": client.username or "",
                            "owner_id": int(owner_id),
                        },
                        "$setOnInsert": {
                            "created_at": datetime.now(timezone.utc)
                        },
                    },
                    upsert=True,
                )
            except Exception:
                LOGGER(__name__).exception(
                    "Could not persist clone metadata for @%s", client.username
                )
                self.clients.pop(fingerprint, None)
                forget_client(client)
                try:
                    await client.stop()
                except Exception:
                    pass
                return False, "Database save failed; the clone was stopped.", None

            return True, f"@{client.username} is live.", client.username

    async def list_clones(self, owner_id):
        if not self.enabled:
            return []
        collection = self._ensure_collection()
        query = {} if int(owner_id) == int(config.OWNER_ID) else {"owner_id": int(owner_id)}
        cursor = collection.find(query).sort("created_at", -1)
        result = []
        async for record in cursor:
            result.append(record)
        return result

    async def remove_clone(self, token, requester_id):
        if not self.enabled:
            return False, "Clone system is not configured."
        token = (token or "").strip()
        collection = self._ensure_collection()
        record = None

        if TOKEN_RE.fullmatch(token):
            record = await collection.find_one({"_id": token_fingerprint(token)})
        elif int(requester_id) == int(config.OWNER_ID):
            username = token.lstrip("@").lower()
            record = await collection.find_one({"username": username})
            if record is None:
                # Older documents may have mixed username case.
                cursor = collection.find({})
                async for item in cursor:
                    if str(item.get("username", "")).lower() == username:
                        record = item
                        break
        else:
            return False, "Only the main owner can remove a clone by username."

        if not record:
            return False, "No registered clone matched that token or username."
        if int(record.get("owner_id", 0)) != int(requester_id) and int(requester_id) != int(config.OWNER_ID):
            return False, "You can only remove clones that you own."

        fingerprint = str(record["_id"])
        try:
            token_plain = self._decrypt(record["token_encrypted"])
        except (InvalidToken, KeyError, ValueError, RuntimeError):
            LOGGER(__name__).exception("Could not decrypt a clone token during removal")
            return False, "Stored token could not be decrypted. Check CLONE_ENCRYPTION_KEY."

        client = self.clients.pop(fingerprint, None)
        if client is not None:
            forget_client(client)
            try:
                await client.stop()
            except Exception:
                LOGGER(__name__).warning("Error while stopping clone client %s", fingerprint[:12])

        try:
            await collection.delete_one({"_id": fingerprint})
        except Exception:
            LOGGER(__name__).exception("Could not delete clone record")
            # Best effort rollback: keep the clone live if its record remains.
            try:
                self.clients[fingerprint] = await self._start_client(
                    token_plain, owner_id=record.get("owner_id", config.OWNER_ID)
                )
            except Exception:
                pass
            return False, "Could not remove the database record; please retry."

        return True, f"Removed @{record.get('username', 'unknown')}."

    async def restore(self):
        if not self.enabled:
            LOGGER(__name__).warning(
                "Clone restore skipped: set CLONE_ENCRYPTION_KEY and MONGO_DB_URI."
            )
            return
        restored = 0
        failed = 0
        try:
            collection = self._ensure_collection()
            async for record in collection.find({}):
                try:
                    token = self._decrypt(record["token_encrypted"])
                    if not TOKEN_RE.fullmatch(token):
                        raise ValueError("stored token has invalid format")
                    await self._start_client(
                        token, owner_id=record.get("owner_id", config.OWNER_ID)
                    )
                    restored += 1
                except Exception as exc:
                    failed += 1
                    LOGGER(__name__).warning(
                        "Could not restore clone record %s: %s",
                        str(record.get("_id", ""))[:12], type(exc).__name__,
                    )
        except Exception as exc:
            LOGGER(__name__).warning(
                "Clone restore could not read MongoDB: %s", type(exc).__name__
            )
            return
        LOGGER(__name__).info("Clone restore complete: %d started, %d failed", restored, failed)

    async def restart_all(self):
        if not self.enabled:
            return 0, 0
        collection = self._ensure_collection()
        records = []
        async for record in collection.find({}):
            records.append(record)
        ok = failed = 0
        for record in records:
            fingerprint = str(record.get("_id", ""))
            old = self.clients.pop(fingerprint, None)
            if old is not None:
                forget_client(old)
                try:
                    await old.stop()
                except Exception:
                    pass
            try:
                token = self._decrypt(record["token_encrypted"])
                await self._start_client(
                    token, owner_id=record.get("owner_id", config.OWNER_ID)
                )
                ok += 1
            except Exception as exc:
                failed += 1
                LOGGER(__name__).warning(
                    "Clone restart failed for %s: %s", fingerprint[:12], type(exc).__name__
                )
        return ok, failed

    async def stop_all(self):
        clients = list(self.clients.values())
        self.clients.clear()
        for client in clients:
            forget_client(client)
            try:
                await client.stop()
            except Exception:
                pass


clone_manager = CloneManager()


async def init_clone_system():
    await clone_manager.restore()


async def shutdown_clone_system():
    await clone_manager.stop_all()
