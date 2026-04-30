"""Enricher — enriquece mensagens com contexto de YouTube e pesquisa web."""
import os, re, json, urllib.request, urllib.error

from modules.youtube_pipeline import extract_video_id, get_youtube_transcript, get_video_info

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
            info = get_video_info(vid_id) if vid_id else {'title': url, 'description': ''}
            extra += f"\n--- Vídeo {i}: {info['title']} ---\n"
            extra += f"URL: {url[:70]}\n"
            if info['description']:
                extra += f"Descrição: {info['description'][:300]}\n"

            whisper_auth = os.environ.get('WHISPER_ENABLED', '') == 'true'
            transcript, err, method, next_step = get_youtube_transcript(url, whisper_authorized=whisper_auth)

            if transcript:
                extra += f"TRANSCRIÇÃO [{method}] ({len(transcript)} chars):\n{transcript[:3000]}\n"
            else:
                extra += f"[Transcrição não disponível: {err}]\n"
                if next_step == 'NEEDS_WHISPER_AUTH':
                    extra += "[Whisper disponível mas requer WHISPER_ENABLED=true no Render]\n"
                elif next_step == 'NEEDS_MANUAL':
                    extra += "[Cola a transcrição manualmente no chat para análise completa]\n"
                # Fallback: pesquisa web
                if vid_id:
                    search_results = web_search(f"{info['title']} resumo análise")
                    if search_results:
                        extra += f"[Análise baseada em pesquisa web sobre o tema]:\n{search_results}\n"
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
