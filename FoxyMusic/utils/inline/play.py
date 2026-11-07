# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────
# Copyright (C) 2021-2022 by Yuki77394@Github, < https://github.com/yuki77394 >.
# and is released under the "GNU v3.0 License Agreement".
# Please see < https://github.com/Yuki77394/FoxyMusic/blob/master/LICENSE >
# All rights reserved.

import math
from typing import Union

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton

from FoxyMusic import app
from FoxyMusic.core.client_context import get_client
from FoxyMusic.utils.formatters import time_to_seconds


def track_markup(_, videoid, user_id, channel, fplay, thumb: Union[bool, str] = None):
    buttons = [
        [
            InlineKeyboardButton(
                text="🎵",
                callback_data=f"MusicStream {videoid}|{user_id}|a|{channel}|{fplay}",
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="🎥",
                callback_data=f"MusicStream {videoid}|{user_id}|v|{channel}|{fplay}",
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="⎘",
                callback_data=f"MusicThumb {videoid}|{user_id}|{channel}|{fplay}",
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="⌯✖",
                callback_data=f"forceclose {videoid}|{user_id}",
                style=ButtonStyle.DANGER,
            ),
        ],
    ]
    return buttons


def _clock(value):
    """Convert seconds or a time string to MM:SS for the player bar."""
    try:
        seconds = int(value) if isinstance(value, (int, float)) else time_to_seconds(str(value))
    except Exception:
        seconds = 0
    seconds = max(0, seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}", seconds


def _player_buttons(chat_id, played="00:00", dur="00:00"):
    played_text, played_seconds = _clock(played)
    duration_text, duration_seconds = _clock(dur)
    if duration_seconds:
        progress = min(10, max(0, round((played_seconds / duration_seconds) * 10)))
    else:
        progress = 0
    bar = "━" * progress + "♡" + "━" * (10 - progress)

    client = get_client()
    username = getattr(client, "username", None) or getattr(app, "username", None)
    add_me_url = f"https://t.me/{username}?startgroup=true" if username else "https://t.me/"

    return [
        [InlineKeyboardButton(
            text=f"{played_text} ━{bar}━ {duration_text}",
            callback_data=f"ADMIN Progress|{chat_id}",
            style=ButtonStyle.PRIMARY,
        )],
        [
            InlineKeyboardButton(text="▷", callback_data=f"ADMIN Resume|{chat_id}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="Ⅱ", callback_data=f"ADMIN Pause|{chat_id}", style=ButtonStyle.DANGER),
            InlineKeyboardButton(text="✿", callback_data=f"ADMIN Filter|{chat_id}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="‣‣I", callback_data=f"ADMIN Skip|{chat_id}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="▢", callback_data=f"ADMIN Stop|{chat_id}", style=ButtonStyle.DANGER),
        ],
        [
            InlineKeyboardButton(text="≪ -20s", callback_data="seek_backward_20", style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(text="↻", callback_data=f"ADMIN Replay|{chat_id}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text="+20s ≫", callback_data="seek_forward_20", style=ButtonStyle.DANGER),
        ],
        [
            InlineKeyboardButton(text="Aᴅᴅ Mᴇ", url=add_me_url, style=ButtonStyle.DANGER),
            InlineKeyboardButton(text="Cʟᴏsᴇ", callback_data="close", style=ButtonStyle.SUCCESS),
        ],
    ]


def _current_track_times(chat_id):
    try:
        from FoxyMusic.misc import db
        playing = db.get(chat_id) or []
        if playing:
            track = playing[0]
            return track.get("played", 0), track.get("dur", "00:00")
    except Exception:
        pass
    return 0, "00:00"


def stream_markup_timer(
    _,
    chat_id,
    played,
    dur,
    autoplay: Union[bool, str] = None,
    thumb: Union[bool, str] = None,
    chat_filter: Union[bool, str] = None,
    more: bool = False,
):
    return _player_buttons(chat_id, played, dur)


def stream_markup(
    _,
    chat_id,
    autoplay: Union[bool, str] = None,
    thumb: Union[bool, str] = None,
    chat_filter: Union[bool, str] = None,
    more: bool = False,
):
    played, dur = _current_track_times(chat_id)
    return _player_buttons(chat_id, played, dur)


def playlist_markup(
    _,
    videoid,
    user_id,
    ptype,
    channel,
    fplay,
    thumb: Union[bool, str] = None,
):
    buttons = [
        [
            InlineKeyboardButton(
                text="🎵",
                callback_data=(
                    f"AlonePlaylists "
                    f"{videoid}|{user_id}|{ptype}|a|{channel}|{fplay}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="🎥",
                callback_data=(
                    f"AlonePlaylists "
                    f"{videoid}|{user_id}|{ptype}|v|{channel}|{fplay}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="⎘",
                callback_data=(
                    f"PlaylistThumb "
                    f"{videoid}|{user_id}|{ptype}|{channel}|{fplay}"
                ),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="✖",
                callback_data=f"forceclose {videoid}|{user_id}",
                style=ButtonStyle.DANGER,
            ),
        ],
    ]

    return buttons


def livestream_markup(
    _,
    videoid,
    user_id,
    mode,
    channel,
    fplay,
    thumb: Union[bool, str] = None,
):
    buttons = [
        [
            InlineKeyboardButton(
                text="🎬",
                callback_data=(
                    f"LiveStream "
                    f"{videoid}|{user_id}|{mode}|{channel}|{fplay}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="⎘",
                callback_data=(
                    f"LiveThumb "
                    f"{videoid}|{user_id}|{mode}|{channel}|{fplay}"
                ),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="✖",
                callback_data=f"forceclose {videoid}|{user_id}",
                style=ButtonStyle.DANGER,
            ),
        ],
    ]

    return buttons


def slider_markup(
    _,
    videoid,
    user_id,
    query,
    query_type,
    channel,
    fplay,
    thumb: Union[bool, str] = None,
):
    query = f"{query[:20]}"

    buttons = [
        [
            InlineKeyboardButton(
                text="🎵",
                callback_data=(
                    f"MusicStream "
                    f"{videoid}|{user_id}|a|{channel}|{fplay}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="🎥",
                callback_data=(
                    f"MusicStream "
                    f"{videoid}|{user_id}|v|{channel}|{fplay}"
                ),
                style=ButtonStyle.PRIMARY,
            ),
        ],
        [
            InlineKeyboardButton(
                text="◁",
                callback_data=(
                    f"slider B|{query_type}|{query}|"
                    f"{user_id}|{channel}|{fplay}"
                ),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="⎘",
                callback_data=(
                    f"SliderThumb "
                    f"{videoid}|{user_id}|{query}|{query_type}|"
                    f"{channel}|{fplay}"
                ),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="▷",
                callback_data=(
                    f"slider F|{query_type}|{query}|"
                    f"{user_id}|{channel}|{fplay}"
                ),
                style=ButtonStyle.SUCCESS,
            ),
        ],
        [
            InlineKeyboardButton(
                text="✖",
                callback_data=f"forceclose {query}|{user_id}",
                style=ButtonStyle.DANGER,
            ),
        ],
    ]

    return buttons
    
