"""
Insura - Text-to-Speech module using Microsoft Edge TTS.

Public API:
    text_to_speech(text: str) -> str
        Generates an MP3 file and returns its filename (not full path).
        The file is written to  <BASE_DIR>/audio/<uuid>.mp3
        so it can be served by Flask's /audio/<filename> route.
"""

import asyncio
import logging
import os
import uuid

import edge_tts

logger = logging.getLogger("insura.tts")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

# Edge TTS voice — Indian English female voice
TTS_VOICE = "en-IN-NeerjaNeural"

# Maximum characters Edge TTS handles reliably in one shot
MAX_TTS_LENGTH = 3000


# ---------------------------------------------------------------------------
# Internal async implementation
# ---------------------------------------------------------------------------


async def _generate_audio(text: str) -> str:
    """
    Async core: call edge_tts, save the file, return its filename.
    Raises on failure so callers can log and return None gracefully.
    """
    # Truncate to avoid Edge TTS failures on very long text
    if len(text) > MAX_TTS_LENGTH:
        logger.warning(
            "TTS input truncated from %d to %d chars.", len(text), MAX_TTS_LENGTH
        )
        text = text[:MAX_TTS_LENGTH]

    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    communicate = edge_tts.Communicate(text=text, voice=TTS_VOICE)
    await communicate.save(filepath)

    # Verify the file was actually written and is non-empty
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        raise RuntimeError(f"TTS produced an empty or missing file: {filepath}")

    logger.info("TTS audio saved: %s (%d bytes)", filename, os.path.getsize(filepath))
    return filename


# ---------------------------------------------------------------------------
# Public synchronous wrapper
# ---------------------------------------------------------------------------


def text_to_speech(text: str) -> str:
    """
    Convert text to speech and return the audio filename.

    Handles the event-loop situation safely:
    - If there is no running loop (normal Flask request context), use asyncio.run().
    - If there IS already a running loop (e.g. inside a Jupyter/async context),
      create a new loop in a separate thread to avoid "cannot run nested" errors.
    """
    if not text or not text.strip():
        raise ValueError("TTS received empty text.")

    try:
        # Standard case — no running event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(_generate_audio(text))

    # Running loop exists — run in a fresh thread-bound event loop
    import concurrent.futures

    def _run_in_thread():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(_generate_audio(text))
        finally:
            new_loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_in_thread)
        return future.result()
