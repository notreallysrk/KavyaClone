# ─────「 𝐅ᴏxʏ 」─────
#    Official Project Source
# ────────────────────────
# Copyright (C) 2021-2022 by Yuki77394@Github, < https://github.com/Yuki77394 >.
# and is released under the "GNU v3.0 License Agreement".
# All rights reserved.

import os

from config import autoclean


async def auto_clean(popped):
    try:
        rem = popped["file"]
        # Remove ONE occurrence of this file from the autoclean list. The
        # same file path may legitimately appear multiple times (e.g. when
        # the same song is queued twice), so we only delete the file from
        # disk when the LAST reference is popped.
        try:
            autoclean.remove(rem)
        except ValueError:
            # File was never in the autoclean list (e.g. cache-restored
            # files). Safe to ignore.
            pass
        count = autoclean.count(rem)
        if count == 0:
            if "vid_" not in rem and "live_" not in rem and "index_" not in rem:
                # ── File-lifecycle protection ─────────────────────────────
                # A background cache-upload task (see FoxyMusic/utils/
                # music_cache.py) may still be reading this file. If so,
                # we MUST NOT delete it now — defer the deletion to the
                # file_refs module, which will os.remove() the file once
                # the last consumer calls release().
                #
                # If no consumer holds a ref, the file is deleted
                # immediately as before (zero behavior change for the
                # existing playback-only flow).
                try:
                    from FoxyMusic.utils import file_refs
                    # Always delegate deletion to the ref manager. Its lock
                    # makes the ref-check + delete decision atomic, avoiding
                    # a race where an upload acquires the file just after a
                    # separate has_refs() check but before os.remove().
                    await file_refs.mark_for_delete(rem)
                except Exception:
                    # Import/runtime failure: retain the legacy best-effort
                    # cleanup rather than leaving temporary audio behind.
                    try:
                        os.remove(rem)
                    except OSError:
                        pass
    except:
        pass
    try:
        mystic = popped.get("mystic")
        if mystic:
            # The message can legitimately be gone already (for example,
            # after a queue transition). Treat deletion as best-effort.
            await mystic.delete()
    except Exception:
        pass
