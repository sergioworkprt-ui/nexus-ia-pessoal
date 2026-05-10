import asyncio
import os
from typing import Callable, Optional
from nexus.services.logger.logger import get_logger

log = get_logger("stt")
WAKE_WORD = "hey nexus"


class STT:
    def __init__(self, on_wake: Optional[Callable] = None):
        self._enabled = os.getenv("STT_ENABLED", "false").lower() == "true"
        self._on_wake = on_wake
        self._running = False

    async def start(self):
        if not self._enabled:
            log.info("STT disabled")
            return
        self._running = True
        log.info(f"STT listening for '{WAKE_WORD}'")
        await self._loop()

    async def _loop(self):
        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            mic = sr.Microphone()
            loop = asyncio.get_event_loop()
            while self._running:
                with mic as src:
                    r.adjust_for_ambient_noise(src, duration=0.3)
                    audio = await loop.run_in_executor(
                        None, lambda: r.listen(src, timeout=3, phrase_time_limit=6)
                    )
                try:
                    text = r.recognize_google(audio).lower()
                    if WAKE_WORD in text:
                        cmd = text.replace(WAKE_WORD, "").strip()
                        log.info(f"Wake word detected. Command: {cmd}")
                        if self._on_wake:
                            await self._on_wake(cmd)
                except Exception:
                    pass
        except Exception as e:
            log.error(f"STT error: {e}")

    def stop(self):
        self._running = False
