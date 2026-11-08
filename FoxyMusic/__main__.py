# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────

import asyncio
import importlib

import static_ffmpeg
from pyrogram import idle
from pytgcalls.exceptions import NoActiveGroupCall

import config
from FoxyMusic import LOGGER, app, userbot
from FoxyMusic.core.call import Alone
from FoxyMusic.misc import sudo
from FoxyMusic.plugins import ALL_MODULES
from FoxyMusic.utils.database import get_banned_users, get_gbanned
from config import BANNED_USERS


async def init():
    static_ffmpeg.add_paths()
    if (
        not config.STRING1
        and not config.STRING2
        and not config.STRING3
        and not config.STRING4
        and not config.STRING5
    ):
        LOGGER(__name__).error("Assistant client variables not defined, exiting...")
        exit()

    await sudo()

    try:
        users = await get_gbanned()
        for user_id in users:
            BANNED_USERS.add(user_id)

        users = await get_banned_users()
        for user_id in users:
            BANNED_USERS.add(user_id)
    except:
        pass

    # ─── Initialize music cache indexes ───────────────────────────────────
    # Creates the unique (video_id, media_type) index on the music_cache
    # collection so duplicate uploads can never produce two records, plus
    # secondary indexes on file_unique_id and normalized_title for fast
    # reverse lookups. Idempotent — safe to call on every boot.
    try:
        from FoxyMusic.utils.database import ensure_music_cache_indexes

        await ensure_music_cache_indexes()

        if getattr(config, "MUSIC_CACHE_ENABLED", True) and getattr(
            config, "STORAGE_CHANNEL_ID", 0
        ):
            LOGGER("FoxyMusic.music_cache").info(
                f"Music cache ENABLED — storage channel={config.STORAGE_CHANNEL_ID}"
            )
        else:
            LOGGER("FoxyMusic.music_cache").info(
                "Music cache DISABLED (STORAGE_CHANNEL_ID not set or "
                "MUSIC_CACHE_ENABLED=false) — bot will run without caching"
            )
    except Exception as e:
        LOGGER("FoxyMusic.music_cache").warning(
            f"Could not initialize music cache indexes: {type(e).__name__}: {e}"
        )

    await app.start()

    for all_module in ALL_MODULES:
        importlib.import_module("FoxyMusic.plugins" + all_module)

    LOGGER("FoxyMusic.plugins").info("Successfully Imported Modules...")

    await userbot.start()
    await Alone.start()

    try:
        await Alone.stream_call(
            "https://te.legra.ph/file/29f784eb49d230ab62e9e.mp4"
        )
    except NoActiveGroupCall:
        LOGGER("FoxyMusic").error(
            "Please turn on the videochat of your log group/channel.\n\n"
            "Stopping Bot..."
        )
        exit()
    except:
        pass

    await Alone.decorators()

    # Restore saved clone clients after plugins and PyTgCalls event handlers are ready.
    from FoxyMusic.core.clone_manager import init_clone_system
    await init_clone_system()

    LOGGER("FoxyMusic").info(
        "Bᴏᴛ Sᴛᴀʀᴛᴇᴅ Sᴜᴄᴄᴇssғᴜʟʟʏ."
    )

    await idle()

    # ─── Graceful shutdown: cancel background stream/cache tasks ─────────
    # Stop prefetch workers first so they cannot start new downloads while
    # cache uploads and the Telegram clients are shutting down.
    try:
        from FoxyMusic.utils.stream.prefetch import cancel_all_prefetch

        cancel_all_prefetch()
    except Exception as e:
        LOGGER("FoxyMusic.shutdown").warning(
            f"Prefetch shutdown issue: {type(e).__name__}"
        )

    try:
        from FoxyMusic.utils.music_cache import cancel_all_uploads

        cancel_all_uploads()
    except Exception as e:
        LOGGER("FoxyMusic.shutdown").warning(
            f"Cache upload shutdown issue: {type(e).__name__}"
        )

    # Stop dynamic clone clients cleanly before the primary bot shuts down.
    try:
        from FoxyMusic.core.clone_manager import shutdown_clone_system
        await shutdown_clone_system()
    except Exception as e:
        LOGGER("FoxyMusic.clones").warning(f"Clone shutdown issue: {type(e).__name__}")

    await app.stop()
    await userbot.stop()

    LOGGER("FoxyMusic").info(
        "Stopping The Foxy Team Bot..."
    )


def main():
    """Console entry point for packaged deployments."""
    asyncio.get_event_loop().run_until_complete(init())


if __name__ == "__main__":
    main()
