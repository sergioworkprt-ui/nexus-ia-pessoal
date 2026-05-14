"""Video Analysis — pipeline completo: transcrição → análise LLM → resumo → fact-check."""
from __future__ import annotations
import asyncio
import glob
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from nexus.services.logger.logger import get_logger

log = get_logger("video_analysis")

_DATA_DIR = Path(os.getenv("NEXUS_HOME", "/opt/nexus")) / "data" / "video"
_TRANSCRIPT_DIR = _DATA_DIR / "transcripts"
_META_DIR = _DATA_DIR / "metadata"

_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|embed/|shorts/)([A-Za-z0-9_-]{11})")
_YT_DOMAIN_RE = re.compile(r"youtube\.com|youtu\.be")

_WHISPER_TIMEOUT = 300.0
_YTDLP_TIMEOUT = 120.0
_LLM_TIMEOUT = 90.0


def _video_id(url: str) -> Optional[str]:
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def is_youtube_url(text: str) -> bool:
    return bool(_YT_DOMAIN_RE.search(text))


class VideoAnalysis:
    def __init__(self):
        self._llm_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self._llm_key = os.getenv("OPENAI_API_KEY", "")
        self._llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._whisper_model = os.getenv("WHISPER_MODEL", "base")

    async def start(self):
        try:
            _TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
            _META_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.warning("[video] erro ao criar dirs: %s", exc)
        log.info("VideoAnalysis iniciado (data_dir: %s)", _DATA_DIR)

    def stop(self):
        pass

    # ── Transcrição ────────────────────────────────────────────────────────────

    async def _transcript_via_api(self, video_id: str) -> Optional[str]:
        """youtube-transcript-api — sem download, mais rápido."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c",
                (
                    "from youtube_transcript_api import YouTubeTranscriptApi; "
                    f"t=YouTubeTranscriptApi.get_transcript('{video_id}',languages=['pt','en']); "
                    "print(' '.join(x['text'] for x in t))"
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            if proc.returncode == 0 and out.strip():
                text = out.decode().strip()
                log.info("[video] transcript via API: %d chars", len(text))
                return text
        except Exception as exc:
            log.debug("[video] transcript_api falhou: %s", exc)
        return None

    async def _transcript_via_ytdlp_subs(self, video_id: str) -> Optional[str]:
        """yt-dlp auto-legendas — sem download de áudio."""
        out_base = f"/tmp/nexus_sub_{video_id}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--skip-download", "--write-auto-sub",
                "--sub-format", "vtt", "--sub-lang", "pt,en",
                "-o", out_base,
                f"https://youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60.0)
            files = glob.glob(f"{out_base}*.vtt")
            if files:
                content = Path(files[0]).read_text(errors="replace")
                lines = []
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
                        continue
                    line = re.sub(r"<[^>]+>", "", line)
                    if line:
                        lines.append(line)
                # Dedup adjacent identical lines (VTT tem sobreposições)
                deduped: list[str] = []
                for line in lines:
                    if not deduped or deduped[-1] != line:
                        deduped.append(line)
                text = " ".join(deduped)
                if text.strip():
                    log.info("[video] transcript via yt-dlp subs: %d chars", len(text))
                    return text
        except Exception as exc:
            log.debug("[video] yt-dlp subs falhou: %s", exc)
        finally:
            for f in glob.glob(f"{out_base}*"):
                try:
                    os.unlink(f)
                except Exception:
                    pass
        return None

    async def _transcript_via_whisper(self, video_id: str) -> Optional[str]:
        """Descarrega áudio e transcreve localmente com whisper."""
        audio_path = f"/tmp/nexus_audio_{video_id}.%(ext)s"
        audio_file: Optional[str] = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp", "--extract-audio", "--audio-format", "mp3",
                "--audio-quality", "5",
                "-o", audio_path,
                f"https://youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, err = await asyncio.wait_for(proc.communicate(), timeout=_YTDLP_TIMEOUT)
            candidates = glob.glob(f"/tmp/nexus_audio_{video_id}.*")
            if not candidates:
                log.warning("[video] whisper: audio download falhou")
                return None
            audio_file = candidates[0]
            log.info("[video] áudio descarregado: %s", audio_file)

            loop = asyncio.get_running_loop()
            af = audio_file
            wmodel = self._whisper_model

            def _run_whisper() -> str:
                import whisper as _w  # noqa: PLC0415
                model = _w.load_model(wmodel)
                result = model.transcribe(af, language="pt")
                return result["text"]

            text = await asyncio.wait_for(
                loop.run_in_executor(None, _run_whisper),
                timeout=_WHISPER_TIMEOUT,
            )
            if text and text.strip():
                log.info("[video] whisper transcreveu: %d chars", len(text))
                return text.strip()
        except asyncio.TimeoutError:
            log.warning("[video] whisper timeout (%ds)", int(_WHISPER_TIMEOUT))
        except ImportError:
            log.warning("[video] whisper nao instalado — instala: pip install openai-whisper")
        except Exception as exc:
            log.warning("[video] whisper erro: %s", exc)
        finally:
            if audio_file:
                try:
                    os.unlink(audio_file)
                except Exception:
                    pass
        return None

    async def get_transcript(self, video_id: str) -> Optional[str]:
        """Cascata: youtube-transcript-api → yt-dlp auto-subs → whisper local."""
        t = await self._transcript_via_api(video_id)
        if t:
            return t
        t = await self._transcript_via_ytdlp_subs(video_id)
        if t:
            return t
        return await self._transcript_via_whisper(video_id)

    # ── LLM ────────────────────────────────────────────────────────────────────

    async def _llm(self, prompt: str) -> str:
        if not self._llm_key:
            return "LLM nao configurado (adiciona OPENAI_API_KEY ao .env)."
        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                r = await client.post(
                    f"{self._llm_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm_key}"},
                    json={
                        "model": self._llm_model,
                        "max_tokens": 1024,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Respondes SEMPRE em portugues europeu (PT-PT). "
                                    "Es o NEXUS, um assistente de analise de conteudo. "
                                    "Se conciso e estruturado."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            log.error("[video] LLM erro: %s", exc)
            return f"Erro ao contactar o modelo: {exc}"

    # ── Análise em paralelo ────────────────────────────────────────────────────

    async def _analyze_parallel(self, transcript: str) -> dict:
        excerpt = transcript[:6000]
        results = await asyncio.gather(
            self._llm(
                f"Faz um resumo claro e conciso deste video em PT-PT (max. 150 palavras):\n\n{excerpt}"
            ),
            self._llm(
                f"Lista os 5 pontos principais deste video em PT-PT. Formato numerado:\n\n{excerpt}"
            ),
            self._llm(
                f"Identifica 3 afirmacoes deste video que merecem verificacao factual. "
                f"Para cada uma indica: verdadeira / duvidosa / falsa + justificacao breve em PT-PT:\n\n{excerpt}"
            ),
            self._llm(
                f"Que conhecimento novo e valioso aprendi com este video? "
                f"Resume em 3 pontos accionaveis em PT-PT:\n\n{excerpt}"
            ),
            return_exceptions=True,
        )

        def _safe(r: object) -> str:
            return r if isinstance(r, str) else "Analise nao disponivel."

        return {
            "resumo": _safe(results[0]),
            "pontos_principais": _safe(results[1]),
            "fact_check": _safe(results[2]),
            "conhecimento": _safe(results[3]),
        }

    # ── Persistência ───────────────────────────────────────────────────────────

    def _save_transcript(self, video_id: str, text: str) -> None:
        try:
            (_TRANSCRIPT_DIR / f"{video_id}.txt").write_text(text, encoding="utf-8")
        except Exception as exc:
            log.warning("[video] erro ao guardar transcricao: %s", exc)

    def _save_metadata(self, video_id: str, data: dict) -> None:
        try:
            (_META_DIR / f"{video_id}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("[video] erro ao guardar metadados: %s", exc)

    def _load_cached(self, video_id: str) -> Optional[dict]:
        path = _META_DIR / f"{video_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    # ── API pública ────────────────────────────────────────────────────────────

    async def analyze(self, url: str, mode: str = "full") -> dict:
        vid = _video_id(url)
        if not vid:
            return {"erro": "URL de YouTube invalido.", "url": url}

        log.info("[video] a analisar: %s (modo=%s)", vid, mode)

        # Cache
        if mode == "full":
            cached = self._load_cached(vid)
            if cached:
                log.info("[video] resultado em cache: %s", vid)
                cached["cache"] = True
                return cached

        # 1. Transcrição
        transcript: Optional[str] = None
        try:
            transcript = await self.get_transcript(vid)
        except Exception as exc:
            log.error("[video] get_transcript erro: %s", exc)

        if not transcript:
            return {
                "erro": (
                    "Nao foi possivel obter a transcricao. "
                    "O video pode nao ter legendas. "
                    "Para suporte completo, instala whisper no VPS: "
                    "pip install openai-whisper"
                ),
                "video_id": vid,
                "url": url,
            }

        try:
            self._save_transcript(vid, transcript)
        except Exception as exc:
            log.warning("[video] save_transcript erro: %s", exc)

        # 2. Análise LLM em paralelo
        analysis: dict = {
            "resumo": "LLM nao configurado.",
            "pontos_principais": "LLM nao configurado.",
            "fact_check": "LLM nao configurado.",
            "conhecimento": "LLM nao configurado.",
        }
        try:
            analysis = await self._analyze_parallel(transcript)
        except Exception as exc:
            log.error("[video] analise LLM erro: %s", exc)

        result = {
            "video_id": vid,
            "url": url,
            "transcript_chars": len(transcript),
            "analisado_em": datetime.utcnow().isoformat(),
            "cache": False,
            **analysis,
        }

        try:
            self._save_metadata(vid, result)
        except Exception as exc:
            log.warning("[video] save_metadata erro: %s", exc)

        return result

    def format_chat_response(self, result: dict) -> str:
        """Formata resultado de analise em resposta PT-PT para o chat."""
        if "erro" in result:
            return f"Nao consegui analisar o video: {result['erro']}"
        chars = result.get("transcript_chars", 0)
        cached_note = " (resultado em cache)" if result.get("cache") else ""
        return (
            f"Video analisado com sucesso{cached_note}. ({chars} caracteres de transcricao)\n\n"
            f"**Resumo:**\n{result.get('resumo', 'N/A')}\n\n"
            f"**Pontos Principais:**\n{result.get('pontos_principais', 'N/A')}\n\n"
            f"**Fact-Check:**\n{result.get('fact_check', 'N/A')}\n\n"
            f"**Conhecimento Aprendido:**\n{result.get('conhecimento', 'N/A')}"
        )
