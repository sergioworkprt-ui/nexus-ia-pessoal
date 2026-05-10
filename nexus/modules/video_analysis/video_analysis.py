"""Video Analysis — YouTube transcript + LLM analysis."""
from __future__ import annotations
import asyncio, os, re, glob
from pathlib import Path
from typing import Optional
import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("video_analysis")


def _video_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


class VideoAnalysis:
    def __init__(self):
        self._llm_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self._llm_key = os.getenv("OPENAI_API_KEY", "")
        self._llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    async def _transcript_via_api(self, video_id: str) -> Optional[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c",
                f"from youtube_transcript_api import YouTubeTranscriptApi; "
                f"t=YouTubeTranscriptApi.get_transcript('{video_id}',languages=['pt','en']); "
                f"print(' '.join(x['text'] for x in t))",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0 and out.strip():
                return out.decode().strip()
        except Exception as e:
            log.debug(f"transcript_api: {e}")
        return None

    async def _transcript_via_ytdlp(self, video_id: str) -> Optional[str]:
        try:
            out_path = f"/tmp/nexus_vid_{video_id}"
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--skip-download", "--write-auto-sub",
                "--sub-format", "vtt", "--sub-lang", "pt,en",
                "-o", out_path, f"https://youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)
            files = glob.glob(f"{out_path}*.vtt")
            if files:
                content = Path(files[0]).read_text(errors="replace")
                lines = [
                    l for l in content.splitlines()
                    if l and not l.startswith("WEBVTT") and "-->" not in l and not l.strip().isdigit()
                ]
                return " ".join(lines)
        except Exception as e:
            log.debug(f"yt-dlp: {e}")
        return None

    async def get_transcript(self, video_id: str) -> Optional[str]:
        t = await self._transcript_via_api(video_id)
        if not t:
            t = await self._transcript_via_ytdlp(video_id)
        return t

    async def _llm(self, prompt: str) -> str:
        if not self._llm_key:
            return "[LLM not configured — add OPENAI_API_KEY]"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self._llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm_key}"},
                    json={"model": self._llm_model, "max_tokens": 2048,
                          "messages": [{"role": "user", "content": prompt}]},
                )
                return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[LLM error: {e}]"

    async def analyze(self, url: str, mode: str = "full") -> dict:
        vid = _video_id(url)
        if not vid:
            return {"error": "Invalid YouTube URL"}
        log.info(f"analyzing video: {vid} mode={mode}")
        transcript = await self.get_transcript(vid)
        if not transcript:
            return {"error": "Could not extract transcript", "video_id": vid,
                    "tip": "Try installing: pip install youtube-transcript-api yt-dlp"}
        excerpt = transcript[:6000]
        result: dict = {"video_id": vid, "transcript_chars": len(transcript)}
        tasks = []
        if mode in ("full", "summary"):
            tasks.append(("summary", self._llm(f"Faz um resumo claro deste vídeo em português:\n\n{excerpt}")))
        if mode in ("full", "concepts"):
            tasks.append(("concepts", self._llm(f"Lista os 10 conceitos mais importantes deste vídeo em português:\n\n{excerpt}")))
        if mode in ("full", "study"):
            tasks.append(("study_plan", self._llm(f"Cria um plano de estudo com 5 exercícios baseado neste conteúdo em português:\n\n{excerpt}")))
        if mode in ("full", "truth"):
            tasks.append(("truth_check", self._llm(f"Identifica afirmações neste vídeo que merecem verificação factual:\n\n{excerpt}")))
        for key, coro in tasks:
            result[key] = await coro
        return result

    async def start(self):
        log.info("VideoAnalysis started")

    def stop(self):
        pass
