"""
NEXUS AI Router — v3

Changes vs v2:
1. Provider order: OpenRouter → Mistral → Gemini → Groq → Cerebras
2. Quota tracking: 429 errors mark provider as quota-exceeded for 5 min
3. Status tracking: _recent_errors, _quota_exceeded, _last_used_provider
4. get_router_status() for /api/status endpoint
5. reload_and_validate() includes mistral
"""
import os, json, time, logging, urllib.request, urllib.error
from collections import deque

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
_recent_errors = deque(maxlen=20)
_quota_exceeded = {}        # provider_name -> unix timestamp when quota was hit
_last_used_provider = None

QUOTA_COOLDOWN = 300        # seconds before retrying a quota-exceeded provider

KEY_MAP = {
    'openrouter': 'OPENROUTER_API_KEY',
    'mistral':    'MISTRAL_API_KEY',
    'gemini':     'GEMINI_API_KEY',
    'groq':       'GROQ_API_KEY',
    'cerebras':   'CEREBRAS_API_KEY',
}

def _get_key(env_var):
    """Reads from os.environ on every call — no cache."""
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

def _is_quota_error(err_str):
    """True if error signals quota/rate-limit exhaustion (HTTP 429)."""
    if not err_str: return False
    e = str(err_str).lower()
    return any(t in e for t in ['429', 'rate_limit', 'quota', 'too many requests',
                                  'rate limit', 'ratelimit'])

def _is_quota_exceeded(provider_name):
    """True if provider is in cooldown after a quota error."""
    ts = _quota_exceeded.get(provider_name.lower())
    if not ts: return False
    if time.time() - ts < QUOTA_COOLDOWN:
        return True
    del _quota_exceeded[provider_name.lower()]
    return False

def _mark_quota_exceeded(provider_name):
    name = provider_name.lower()
    _quota_exceeded[name] = time.time()
    logger.warning(f"Provider {name} marked quota-exceeded for {QUOTA_COOLDOWN}s")

def _should_continue(err_str):
    """True = transient error, try next provider."""
    if not err_str: return False
    e = str(err_str)
    transient = ['503', '429', '404', '408', '400', '403', '401',
                 'TIMEOUT', 'DNS_ERROR', 'URL_ERROR', 'JSON_PARSE',
                 'overloaded', 'rate_limit', 'quota', 'unavailable',
                 'capacity', 'not found', 'model_not_found']
    return any(t in e for t in transient)

# ── Provider functions ────────────────────────────────────────────────────

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
        'nvidia/llama-3.1-nemotron-70b-instruct:free',
        'openchat/openchat-7b:free',
        'gryphe/mythomist-7b:free',
        'undi95/toppy-m-7b:free',
        'nousresearch/nous-capybara-7b:free',
    ]
    last_err = "sem modelos tentados"

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            "https://openrouter.ai/api/v1/chat/completions", headers, body)
        if err:
            last_err = f"{model}: {err}"
            logger.debug(f"OpenRouter {model}: {err}")
            if _is_quota_error(err):
                return None, f"HTTP 429: {err}"  # bubble quota error up
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
    models   = ['mistral-small-latest', 'open-mistral-7b', 'open-mixtral-8x7b']
    last_err = "sem modelos tentados"

    for model in models:
        body = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request("https://api.mistral.ai/v1/chat/completions", headers, body)
        if err:
            last_err = f"{model}: {err}"
            logger.debug(f"Mistral {model}: {err}")
            if _is_quota_error(err):
                return None, f"HTTP 429: {err}"
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Mistral OK: {model}")
                return text, None
        except Exception as e:
            last_err = f"{model}: parse {e}"
            continue

    return None, f"Mistral: {last_err}"

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
            if _is_quota_error(err):
                return None, f"HTTP 429: {err}"
            continue
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
            if _is_quota_error(err):
                return None, f"HTTP 429: {err}"
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
            if _is_quota_error(err):
                return None, f"HTTP 429: {err}"
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

# ── Validation & status ────────────────────────────────────────────────────

def validate_api(provider_name):
    """Tests if an API is reachable. Returns (ok, status, ms)."""
    t0  = time.time()
    fns = {
        'openrouter': _try_openrouter,
        'mistral':    _try_mistral,
        'gemini':     _try_gemini,
        'groq':       _try_groq,
        'cerebras':   _try_cerebras,
    }
    name = provider_name.lower()
    fn   = fns.get(name)
    if not fn: return False, f"Provider '{name}' desconhecido", 0

    resp, err = fn([{'role': 'user', 'content': 'Responde só: OK'}], 'Responde só: OK')
    ms = int((time.time() - t0) * 1000)
    ok = bool(resp)
    _last_validation[name] = {
        'ok': ok, 'status': 'OK' if ok else err,
        'ts': time.time(), 'ms': ms
    }
    return ok, ('OK' if ok else str(err)), ms

def get_validation_status():
    """Returns key presence + last test result for all providers."""
    status = {}
    for name, env_var in KEY_MAP.items():
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

def get_router_status():
    """Full status dict for the /api/status endpoint."""
    providers = {}
    for name, env_var in KEY_MAP.items():
        key    = _get_key(env_var)
        cached = _last_validation.get(name, {})
        quota_ts = _quota_exceeded.get(name)
        remaining = max(0, QUOTA_COOLDOWN - (time.time() - quota_ts)) if quota_ts else 0
        providers[name] = {
            'key_set':        bool(key),
            'key_prefix':     (key[:12] + '...') if key else 'NOT SET',
            'last_ok':        cached.get('ok'),
            'last_status':    cached.get('status', 'não testado'),
            'last_ms':        cached.get('ms', 0),
            'last_tested_ts': cached.get('ts'),
            'quota_exceeded': bool(quota_ts and time.time() - quota_ts < QUOTA_COOLDOWN),
            'quota_reset_in': int(remaining),
        }

    active = [n for n, v in providers.items() if v['key_set'] and not v['quota_exceeded']]
    quota_saver = any(v['quota_exceeded'] for v in providers.values())

    return {
        'providers':       providers,
        'mode':            _last_used_provider or 'none',
        'fallback_active': bool(_last_used_provider and _last_used_provider.lower() != 'openrouter'),
        'active_providers': active,
        'quota_saver_mode': quota_saver,
        'recent_errors':   list(_recent_errors),
        'timestamps': {
            'server_time':     time.time(),
            'server_time_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
    }

def reload_and_validate():
    """Clears cache and re-validates all APIs."""
    _last_validation.clear()
    _quota_exceeded.clear()
    results = {}
    for name in list(KEY_MAP.keys()):
        ok, status, ms = validate_api(name)
        results[name] = {'ok': ok, 'status': status, 'ms': ms}
        logger.info(f"reload [{name}]: {'OK' if ok else status}")
    return results

# ── Main router ────────────────────────────────────────────────────────────

def get_ai_response(messages, memory_context=''):
    """Router — reads keys from os.environ on every call, no cache."""
    global _last_used_provider
    system    = SYSTEM_PROMPT + (memory_context or '')
    providers = [
        ('OpenRouter', _try_openrouter),
        ('Mistral',    _try_mistral),
        ('Gemini',     _try_gemini),
        ('Groq',       _try_groq),
        ('Cerebras',   _try_cerebras),
    ]
    errors   = []
    deadline = time.time() + 90   # global budget — avoids exceeding gunicorn timeout

    for name, fn in providers:
        if time.time() > deadline:
            logger.warning(f"Router: 90s budget exhausted before trying {name}")
            errors.append(f"{name}: orçamento de tempo esgotado")
            break

        if _is_quota_exceeded(name.lower()):
            logger.info(f"Router: skipping {name} (quota cooldown)")
            errors.append(f"{name}: quota em cooldown")
            continue

        try:
            response, err = fn(messages, system)
        except Exception as e:
            err      = f"exception: {e}"
            response = None
            logger.error(f"Router [{name}] exception: {e}")

        if response:
            logger.info(f"AI response via {name} ({len(response)} chars)")
            _last_used_provider = name
            return response, name

        error_entry = {
            'provider': name, 'error': str(err),
            'ts': time.time(),
            'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        _recent_errors.append(error_entry)

        if _is_quota_error(str(err)):
            _mark_quota_exceeded(name.lower())

        errors.append(f"{name}: {err}")
        logger.debug(f"Router [{name}] failed: {err}")

    # All providers failed
    not_set    = [n for n, _ in providers if not _get_key(KEY_MAP.get(n.lower(), n.upper() + '_API_KEY'))]
    configured = [n for n, _ in providers if _get_key(KEY_MAP.get(n.lower(), n.upper() + '_API_KEY'))]

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
