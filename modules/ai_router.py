"""
NEXUS AI Router — v2 (bugs corrigidos)

Bugs corrigidos vs v1:
1. Groq/Cerebras: 403 causava return imediato em vez de continue para próximo modelo
2. Gemini: apenas 503/429/404 eram ignorados; 400/500 saíam da função
3. OpenRouter: erros não eram logados, falhas silenciosas
4. Sem auto-correção / reload de chaves
"""
import os, json, time, logging, urllib.request, urllib.error
logger = logging.getLogger('nexus.ai_router')

SYSTEM_PROMPT = """És uma IA pessoal e autónoma chamada NEXUS. Trabalhas exclusivamente para o utilizador Sergio, de Paredes, Porto, Portugal.

A tua missão:
1. GERAR RENDIMENTO online através de métodos legais e éticos
2. AUTOMATIZAR tarefas repetitivas e de pesquisa
3. CRIAR conteúdo de qualidade
4. PLANEAR e EXECUTAR estratégias de negócio digital
5. APRENDER e EVOLUIR continuamente

Quando sugeres formas de gerar rendimento:
- Sê específico e realista
- Indica esforço necessário (horas/semana)
- Potencial em euros/mês
- Primeiros 3 passos de ação imediata

Idioma: SEMPRE Português de Portugal.
Tom: direto, prático, orientado a resultados."""

_last_validation = {}

def _get_key(env_var):
    """Lê SEMPRE do os.environ — sem cache."""
    return os.environ.get(env_var, '').strip()

def _make_request(url, headers, body, timeout=12):
    data = json.dumps(body).encode('utf-8')
    req  = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace')), None
    except urllib.error.HTTPError as e:
        body_raw = ''
        try: body_raw = e.read().decode('utf-8', errors='replace')[:300]
        except Exception: pass
        return None, f"HTTP {e.code}: {body_raw}"
    except urllib.error.URLError as e:
        r = str(e.reason)
        if 'timed out' in r.lower(): return None, "TIMEOUT"
        if 'Name or service' in r or 'getaddrinfo' in r: return None, "DNS_ERROR"
        return None, f"URL_ERROR: {r[:100]}"
    except json.JSONDecodeError as e:
        return None, f"JSON_PARSE: {e}"
    except Exception as e:
        return None, f"ERROR: {str(e)[:100]}"

def _should_continue(err_str):
    """
    True = erro transitório, tenta próximo modelo.
    CORRECÇÃO CRÍTICA: 403 num modelo específico NÃO significa chave inválida —
    significa que esse modelo específico bloqueou. A chave pode ser válida noutros modelos.
    """
    if not err_str: return False
    e = str(err_str)
    transient = ['503', '429', '404', '408', '400', '403', '401',
                 'TIMEOUT', 'DNS_ERROR', 'URL_ERROR', 'JSON_PARSE',
                 'overloaded', 'rate_limit', 'quota', 'unavailable',
                 'capacity', 'not found', 'model_not_found']
    return any(t in e for t in transient)

def _try_gemini(messages, system):
    key = _get_key('GEMINI_API_KEY')
    if not key: return None, "GEMINI_API_KEY não definida"

    contents = [{'role': 'user' if m['role']=='user' else 'model',
                 'parts': [{'text': m['content']}]} for m in messages]
    if not contents or contents[0]['role'] != 'user':
        contents.insert(0, {'role': 'user', 'parts': [{'text': 'Olá'}]})

    models   = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    last_err = "sem modelos tentados"

    for model_name in models:
        url  = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model_name}:generateContent?key={key}")
        body = {
            'system_instruction': {'parts': [{'text': system}]},
            'contents': contents,
            'generationConfig': {'maxOutputTokens': 4096, 'temperature': 0.7}
        }
        result, err = _make_request(url, {'Content-Type': 'application/json'}, body)
        if err:
            last_err = f"{model_name}: {err}"
            logger.debug(f"Gemini {model_name}: {err}")
            continue  # sempre continua — CORRECÇÃO
        try:
            text = result['candidates'][0]['content']['parts'][0]['text']
            if text:
                logger.info(f"Gemini OK: {model_name}")
                return text, None
        except Exception as e:
            last_err = f"{model_name}: parse {e}"
            continue

    return None, f"Gemini: {last_err}"

def _try_groq(messages, system):
    key = _get_key('GROQ_API_KEY')
    if not key: return None, "GROQ_API_KEY não definida"

    headers  = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs     = [{'role': 'system', 'content': system}] + [
                {'role': m['role'], 'content': m['content']} for m in messages]
    models   = ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile',
                'llama3-70b-8192', 'llama3-8b-8192', 'mixtral-8x7b-32768']
    last_err = "sem modelos tentados"

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            "https://api.groq.com/openai/v1/chat/completions", headers, body)
        if err:
            last_err = f"{model}: {err}"
            logger.debug(f"Groq {model}: {err}")
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Groq OK: {model}")
                return text, None
        except Exception as e:
            last_err = f"{model}: parse {e}"
            continue

    return None, f"Groq: {last_err}"

def _try_cerebras(messages, system):
    key = _get_key('CEREBRAS_API_KEY')
    if not key: return None, "CEREBRAS_API_KEY não definida"

    headers  = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs     = [{'role': 'system', 'content': system}] + [
                {'role': m['role'], 'content': m['content']} for m in messages]
    models   = ['llama-3.3-70b', 'llama3.1-70b', 'llama3.1-8b']
    last_err = "sem modelos tentados"

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            "https://api.cerebras.ai/v1/chat/completions", headers, body)
        if err:
            last_err = f"{model}: {err}"
            logger.debug(f"Cerebras {model}: {err}")
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Cerebras OK: {model}")
                return text, None
        except Exception as e:
            last_err = f"{model}: parse {e}"
            continue

    return None, f"Cerebras: {last_err}"

def _try_openrouter(messages, system):
    key = _get_key('OPENROUTER_API_KEY')
    if not key: return None, "OPENROUTER_API_KEY não definida"

    headers = {
        'Content-Type':  'application/json',
        'Authorization': f'Bearer {key}',
        'HTTP-Referer':  'https://nexus-ia-pessoal.onrender.com',
        'X-Title':       'NEXUS IA Pessoal'
    }
    msgs   = [{'role': 'system', 'content': system}] + [
              {'role': m['role'], 'content': m['content']} for m in messages]
    models = [
        'google/gemini-flash-1.5',
        'meta-llama/llama-3.3-70b-instruct:free',
        'mistralai/mistral-7b-instruct:free',
        'microsoft/phi-3-medium-128k-instruct:free',
        'qwen/qwen-2-7b-instruct:free',
    ]
    last_err = "sem modelos tentados"

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            "https://openrouter.ai/api/v1/chat/completions", headers, body)
        if err:
            last_err = f"{model}: {err}"
            logger.debug(f"OpenRouter {model}: {err}")
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"OpenRouter OK: {model}")
                return text, None
        except Exception as e:
            last_err = f"{model}: parse {e}"
            continue

    return None, f"OpenRouter: {last_err}"

def _try_mistral(messages, system):
    key = _get_key('MISTRAL_API_KEY')
    if not key: return None, "MISTRAL_API_KEY não definida"

    headers  = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs     = [{'role': 'system', 'content': system}] + [
                {'role': m['role'], 'content': m['content']} for m in messages]
    body     = {'model': 'mistral-small-latest', 'messages': msgs,
                 'max_tokens': 4096, 'temperature': 0.7}
    result, err = _make_request("https://api.mistral.ai/v1/chat/completions", headers, body)
    if err: return None, f"Mistral: {err}"
    try:
        text = result['choices'][0]['message']['content']
        if text: return text, None
    except Exception as e:
        return None, f"Mistral: parse {e}"
    return None, "Mistral: resposta vazia"

# ── Validação e reload ────────────────────────────────────────────────────
def validate_api(provider_name):
    """Testa se uma API está acessível. Retorna (ok, status, ms)."""
    t0  = time.time()
    fns = {'gemini': _try_gemini, 'groq': _try_groq, 'cerebras': _try_cerebras,
           'openrouter': _try_openrouter, 'mistral': _try_mistral}
    name = provider_name.lower()
    fn   = fns.get(name)
    if not fn: return False, f"Provider '{name}' desconhecido", 0

    resp, err = fn([{'role': 'user', 'content': 'Responde só: OK'}], 'Responde só: OK')
    ms = int((time.time() - t0) * 1000)
    ok = bool(resp)
    _last_validation[name] = {'ok': ok, 'status': 'OK' if ok else err, 'ts': time.time(), 'ms': ms}
    return ok, ('OK' if ok else str(err)), ms

def get_validation_status():
    """Estado de todas as chaves (lidas do ambiente em tempo real)."""
    key_map = {'gemini': 'GEMINI_API_KEY', 'groq': 'GROQ_API_KEY',
               'cerebras': 'CEREBRAS_API_KEY', 'openrouter': 'OPENROUTER_API_KEY',
               'mistral': 'MISTRAL_API_KEY'}
    status = {}
    for name, env_var in key_map.items():
        key    = _get_key(env_var)
        cached = _last_validation.get(name, {})
        status[name] = {
            'key_set':     bool(key),
            'key_prefix':  (key[:12] + '...') if key else 'NOT SET',
            'last_ok':     cached.get('ok'),
            'last_status': cached.get('status', 'não testado'),
            'last_ms':     cached.get('ms', 0),
        }
    return status

def reload_and_validate():
    """Limpa cache e re-valida todas as APIs."""
    _last_validation.clear()
    results = {}
    for name in ['gemini', 'groq', 'cerebras', 'openrouter']:
        ok, status, ms = validate_api(name)
        results[name] = {'ok': ok, 'status': status, 'ms': ms}
        logger.info(f"reload [{name}]: {'OK' if ok else status}")
    return results

# ── Router principal ───────────────────────────────────────────────────────
def get_ai_response(messages, memory_context=''):
    """Router — lê chaves do os.environ em cada chamada, sem cache."""
    system    = SYSTEM_PROMPT + (memory_context or '')
    providers = [
        ('Gemini',     _try_gemini),
        ('Groq',       _try_groq),
        ('Cerebras',   _try_cerebras),
        ('OpenRouter', _try_openrouter),
        ('Mistral',    _try_mistral),
    ]
    errors  = []
    # Orçamento global de 90s — evita exceder o timeout do gunicorn (120s)
    deadline = time.time() + 90

    for name, fn in providers:
        if time.time() > deadline:
            logger.warning(f"Router: orçamento de 90s esgotado antes de tentar {name}")
            errors.append(f"{name}: orçamento de tempo esgotado")
            break
        try:
            response, err = fn(messages, system)
        except Exception as e:
            err = f"exception: {e}"
            response = None
            logger.error(f"Router [{name}] exception: {e}")

        if response:
            logger.info(f"AI response via {name} ({len(response)} chars)")
            return response, name

        errors.append(f"{name}: {err}")
        logger.debug(f"Router [{name}] failed: {err}")

    # Todos falharam
    not_set    = [n for n, _ in providers if not _get_key(n.upper() + '_API_KEY')]
    configured = [n for n, _ in providers if _get_key(n.upper() + '_API_KEY')]

    lines = ["⚠️ Nenhuma IA respondeu neste momento.\n"]
    if not_set:    lines.append(f"**Sem chave:** {', '.join(not_set)}")
    if configured: lines.append(f"**Com chave mas com erro:** {', '.join(configured)}")
    lines.append("\n**Erros:**")
    for e in errors: lines.append(f"• {e}")
    lines.append(
        "\n**Comandos de diagnóstico:**\n"
        "• `recarregar ia` — limpa cache e re-valida\n"
        "• `status ia` — diagnóstico completo\n"
        "• Comandos internos funcionam sem IA (mostra limites, liga xtb, etc.)"
    )
    logger.error(f"All providers failed: {errors}")
    return "\n".join(lines), "none"
