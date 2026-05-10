import asyncio
import os
from nexus.services.logger.logger import get_logger

log = get_logger("tts")


class TTS:
    def __init__(self):
        self._engine = os.getenv("TTS_ENGINE", "gtts")
        self._enabled = os.getenv("TTS_ENABLED", "false").lower() == "true"

    async def speak(self, text: str):
        if not self._enabled:
            return
        log.info(f"Speaking: {text[:60]}")
        try:
            if self._engine == "gtts":
                await self._gtts(text)
            elif self._engine == "elevenlabs":
                await self._elevenlabs(text)
        except Exception as e:
            log.error(f"TTS error: {e}")

    async def _gtts(self, text: str):
        from gtts import gTTS
        import tempfile
        tts = gTTS(text=text, lang="en", slow=False)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tts.save(f.name)
            proc = await asyncio.create_subprocess_exec(
                "mpg123", "-q", f.name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            os.unlink(f.name)

    async def _elevenlabs(self, text: str):
        import httpx
        key = os.getenv("ELEVENLABS_API_KEY", "")
        vid = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
        async with httpx.AsyncClient() as c:
            r = await c.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                headers={"xi-api-key": key},
                json={"text": text, "model_id": "eleven_monolingual_v1"},
            )
        with open("/tmp/nexus_tts.mp3", "wb") as f:
            f.write(r.content)
        proc = await asyncio.create_subprocess_exec(
            "mpg123", "-q", "/tmp/nexus_tts.mp3",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
