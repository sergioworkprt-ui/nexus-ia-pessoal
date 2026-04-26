"""Enricher — enriquece mensagens com contexto de YouTube e pesquisa web."""
import os, re, json, urllib.request, urllib.error

def extract_video_id(url):
    for pattern in [r'(?:v=)([\w-]{11})', r'(?:youtu\.be/)([\w-]{11})',
                    r'(?:embed/)([\w-]{11})', r'(?:shorts/)([\w-]{11})']:
        m = re.search(pattern, url)
        if m: return m.group(1)
    return url.strip() if len(url.strip()) == 11 else None

def get_youtube_transcript(url):
    video_id = extract_video_id(url)
    if not video_id:
        return None, f"ID inválido: {url[:60]}"
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            tlist = YouTubeTranscriptApi.get_transcript(video_id, languages=['pt', 'pt-PT', 'pt-BR'])
        except Exception:
            tlist = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US', 'en-GB'])
        text = ' '.join([t['text'] for t in tlist])
        return text[:6000], None
    except Exception as e:
        err = str(e)
        if 'No transcripts' in err or 'Could not retrieve' in err:
            return None, "Sem legendas disponíveis neste vídeo"
        return None, f"Erro: {err[:100]}"

def web_search(query):
    key = os.environ.get('SERPER_API_KEY', '')
    if not key: return None
    try:
        data = json.dumps({'q': query, 'gl': 'pt', 'hl': 'pt', 'num': 5}).encode()
        req = urllib.request.Request(
            "https://google.serper.dev/search", data=data,
            headers={'X-API-KEY': key, 'Content-Type': 'application/json'}, method='POST'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
        items = []
        for r in result.get('organic', [])[:5]:
            items.append(f"• {r.get('title','')}: {r.get('snippet','')} ({r.get('link','')})")
        return "\n".join(items) if items else None
    except Exception:
        return None

def detect_and_enrich(user_message, db_path, user_id):
    """Enriquece a mensagem com contexto adicional."""
    msg_lower = user_message.lower()
    extra = ""

    # Deteta YouTube
    yt_urls = [u for u in re.findall(r'https?://[^\s<>"]+', user_message)
               if 'youtube' in u or 'youtu.be' in u]

    if yt_urls:
        extra += f"\n\n=== ANÁLISE DE {len(yt_urls)} VÍDEO(S) YOUTUBE ===\n"
        for i, url in enumerate(yt_urls[:6], 1):
            vid_id = extract_video_id(url)
            extra += f"\n--- Vídeo {i}: {url[:70]} ---\n"
            transcript, err = get_youtube_transcript(url)
            if transcript:
                extra += f"TRANSCRIÇÃO ({len(transcript)} chars):\n{transcript[:2500]}\n"
            else:
                extra += f"[Sem transcrição: {err}]\n"
                # Tenta pesquisa web sobre o vídeo como fallback
                search_results = web_search(f"youtube video {vid_id} summary")
                if search_results:
                    extra += f"[Pesquisa web sobre o vídeo]:\n{search_results}\n"
        extra += "\n=== FIM DOS VÍDEOS ===\n"

    # Deteta pedido de pesquisa web (sem YouTube)
    elif os.environ.get('SERPER_API_KEY'):
        search_triggers = ['pesquisa', 'procura', 'busca', 'search', 'o que é',
                           'como funciona', 'notícias', 'preço', 'quanto custa',
                           'melhor', 'top ', 'ranking', 'atual', 'hoje']
        if any(t in msg_lower for t in search_triggers):
            # Extrai query
            query = user_message
            for prefix in ['pesquisa sobre ', 'pesquisa ', 'procura ', 'busca ']:
                if msg_lower.startswith(prefix):
                    query = user_message[len(prefix):]
                    break
            results = web_search(query[:200])
            if results:
                extra += f"\n\nRESULTADOS DA PESQUISA WEB:\n{results}\n"

    return extra
