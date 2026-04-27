"""
YouTube Pipeline completa:
1. youtube-transcript-api (grátis, sem downloads)
2. yt-dlp + Whisper local (se autorizado)
3. Serviço externo gratuito
4. Transcrição manual
"""
import os, re, json, logging, tempfile, urllib.request

logger = logging.getLogger('nexus.youtube')


def extract_video_id(url):
    for pattern in [r'(?:v=)([\w-]{11})', r'(?:youtu\.be/)([\w-]{11})',
                    r'(?:embed/)([\w-]{11})', r'(?:shorts/)([\w-]{11})']:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    s = url.strip()
    return s if len(s) == 11 else None


# ── Método 1: youtube-transcript-api ──────────────────────────────────────
def try_transcript_api(video_id):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        for langs in [['pt', 'pt-PT', 'pt-BR'], ['en', 'en-US', 'en-GB'], None]:
            try:
                if langs:
                    tlist = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
                else:
                    # tenta qualquer idioma disponível
                    transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
                    tlist = list(transcripts)[0].fetch()
                text = ' '.join(t['text'] for t in tlist).strip()
                if text and len(text) > 50:
                    logger.info(f"Transcrição obtida via API: {video_id} ({len(text)} chars)")
                    return text[:8000], None
            except (NoTranscriptFound, KeyError):
                continue
        return None, "Sem transcrição disponível via API"
    except TranscriptsDisabled:
        return None, "Transcrições desativadas pelo canal"
    except Exception as e:
        return None, f"transcript-api erro: {str(e)[:100]}"


# ── Método 2: yt-dlp + Whisper ────────────────────────────────────────────
def try_whisper_pipeline(video_id, authorized=False):
    """Usa yt-dlp para baixar áudio e Whisper para transcrever."""
    if not authorized:
        return None, "NEEDS_AUTHORIZATION"

    try:
        import yt_dlp
    except ImportError:
        return None, "yt-dlp não instalado (adiciona ao requirements.txt)"

    try:
        import whisper
    except ImportError:
        return None, "openai-whisper não instalado (adiciona ao requirements.txt)"

    tmp_dir = tempfile.mkdtemp()
    audio_path = os.path.join(tmp_dir, f"{video_id}.mp3")

    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(tmp_dir, f"{video_id}.%(ext)s"),
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '64'}],
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(audio_path):
            mp3s = [f for f in os.listdir(tmp_dir) if f.endswith('.mp3')]
            if not mp3s:
                return None, "yt-dlp: áudio não descarregado"
            audio_path = os.path.join(tmp_dir, mp3s[0])

        logger.info(f"Áudio descarregado: {audio_path}")
        model = whisper.load_model("tiny")  # tiny = mais rápido, menos RAM
        result = model.transcribe(audio_path, language=None, fp16=False)
        text = result.get("text", "").strip()

        # Limpa
        try:
            import shutil
            shutil.rmtree(tmp_dir)
        except Exception:
            pass

        if text and len(text) > 50:
            logger.info(f"Whisper transcrição: {len(text)} chars")
            return text[:8000], None
        return None, "Whisper: transcrição vazia"

    except Exception as e:
        logger.error(f"Whisper pipeline erro: {e}")
        return None, f"Whisper erro: {str(e)[:150]}"


# ── Método 3: Serviço externo gratuito ────────────────────────────────────
def try_external_service(video_id):
    """Tenta obter transcrição via serviços externos gratuitos."""
    # YoutubeTranscript.io — API pública sem key
    try:
        url = f"https://youtubetranscript.com/?server_vid2={video_id}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        # Extrai texto dos spans
        texts = re.findall(r'<text[^>]*>([^<]+)</text>', html)
        if not texts:
            texts = re.findall(r'<span[^>]*class="[^"]*transcript[^"]*"[^>]*>([^<]+)</span>', html)
        if texts:
            text = ' '.join(t.strip() for t in texts if t.strip())
            if len(text) > 50:
                logger.info(f"Transcrição via serviço externo: {len(text)} chars")
                return text[:8000], None
    except Exception as e:
        logger.warning(f"Serviço externo erro: {e}")

    return None, "Serviço externo não disponível"


# ── Pipeline principal ────────────────────────────────────────────────────
def get_youtube_transcript(url, whisper_authorized=False):
    """
    Pipeline completa de transcrição YouTube.
    Retorna: (texto, erro, método_usado, próximo_passo)
    """
    video_id = extract_video_id(url)
    if not video_id:
        return None, f"ID inválido: {url[:60]}", None, None

    # Método 1: API oficial
    text, err = try_transcript_api(video_id)
    if text:
        return text, None, "transcript-api", None

    logger.info(f"API falhou ({err}), a tentar Whisper...")

    # Método 2: Whisper (requer autorização)
    text, err = try_whisper_pipeline(video_id, authorized=whisper_authorized)
    if err == "NEEDS_AUTHORIZATION":
        return None, "Transcrição não disponível via API", "none", "NEEDS_WHISPER_AUTH"
    if text:
        return text, None, "whisper", None

    logger.info(f"Whisper falhou ({err}), a tentar serviço externo...")

    # Método 3: Serviço externo
    text, err = try_external_service(video_id)
    if text:
        return text, None, "external", None

    # Método 4: Falha total
    return None, f"Sem transcrição disponível ({err})", "none", "NEEDS_MANUAL"


def get_video_info(video_id):
    """Obtém título e descrição do vídeo sem transcrição."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        title = re.search(r'"title":"([^"]+)"', html)
        desc = re.search(r'"shortDescription":"([^"]{10,500})"', html)

        return {
            'title': title.group(1) if title else f"Vídeo {video_id}",
            'description': desc.group(1).replace('\\n', ' ') if desc else ''
        }
    except Exception:
        return {'title': f"Vídeo {video_id}", 'description': ''}
