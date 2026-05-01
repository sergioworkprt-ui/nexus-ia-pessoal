"""
NEXUS AI Router — v3

Providers por ordem de fiabilidade no Render:
1. Gemini    — Google API direta, sem Cloudflare, funciona em datacenters
2. OpenRouter — infra própria, funciona em datacenters, muitos modelos grátis
3. Mistral   — funciona se MISTRAL_API_KEY estiver definida
4. Groq      — BLOQUEADO por Cloudflare no Render Free (error 1010); tentado por último
5. Cerebras  — BLOQUEADO por Cloudflare no Render Free (error 1010); tentado por último

NOTA GROQ/CEREBRAS: O erro "HTTP 403: error code: 1010" é o Cloudflare a bloquear
IPs de datacenters. Não é problema de chave. Não há solução no código — precisas de
Render pago (IPs dedicados) ou mudar de host.
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
_last_used_provider = None

def _get_key(env_var):
    return os.environ.get(env_var, '').strip()

def _make_request(url, headers, body, timeout=12):
    data = json.dumps(body).encode('utf-8')
    req  = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace')), None
    except urllib.error.HTTPError as e:
        body_raw = ''
        try: body_raw = e.read().decode('utf-8', errors='replace')[:200]
        except Exception: pass
        return None, f"HTTP {e.code}: {body_raw}"
    except urllib.error.URLError as e:
        r = str(e.reason)
        if 'timed out' in r.lower(): return None, "TIMEOUT"
        if 'Name or service' in r or 'getaddrinfo' in r: return None, "DNS_ERROR"
        return None, f"URL_ERROR: {r[:80]}"
    except json.JSONDecodeError as e:
        return None, f"JSON_PARSE: {e}"
    except Exception as e:
        return None, f"ERROR: {str(e)[:80]}"

# ── Gemini ────────────────────────────────────────────────────────────────────
def _try_gemini(messages, system):
    key = _get_key('GEMINI_API_KEY')
    if not key: return None, "GEMINI_API_KEY não definida"

    contents = []
    for m in messages:
        role = 'user' if m['role'] == 'user' else 'model'
        contents.append({'role': role, 'parts': [{'text': m['content']}]})
    if not contents or contents[0]['role'] != 'user':
        contents.insert(0, {'role': 'user', 'parts': [{'text': 'Olá'}]})

    models = [
        'gemini-2.0-flash-lite',
        'gemini-2.0-flash',
        'gemini-1.5-flash',
        'gemini-1.5-flash-8b',
    ]
    errors = []

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
            errors.append(f"{model_name}: {err}")
            logger.debug(f"Gemini {model_name}: {err}")
            # Quota esgotada (429) é por projeto, não por modelo —
            # tentar outros modelos da mesma chave é inútil; sai imediatamente
            if '429' in str(err) and ('quota' in str(err).lower() or 'exceeded' in str(err).lower()):
                logger.warning("Gemini: cota diária esgotada — a saltar para próximo provider")
                break
            continue
        try:
            text = result['candidates'][0]['content']['parts'][0]['text']
            if text:
                logger.info(f"Gemini OK: {model_name}")
                return text, None
        except Exception as e:
            errors.append(f"{model_name}: parse {e}")
            continue

    first = errors[0] if errors else "sem erro"
    tail  = f' (+{len(errors)-1} mais)' if len(errors) > 1 else ''
    return None, f"Gemini: {first}{tail}"

# ── OpenRouter ────────────────────────────────────────────────────────────────
# Lista ampla para máxima cobertura — modelos menores são mais disponíveis
def _try_openrouter(messages, system):
    key = _get_key('OPENROUTER_API_KEY')
    if not key: return None, "OPENROUTER_API_KEY não definida"

    headers = {
        'Content-Type':  'application/json',
        'Authorization': f'Bearer {key}',
        'HTTP-Referer':  'https://nexus-ia-pessoal.onrender.com',
        'X-Title':       'NEXUS IA Pessoal'
    }
    msgs = [{'role': 'system', 'content': system}] + [
           {'role': m['role'], 'content': m['content']} for m in messages]

    # Modelos com endpoints ativos no OpenRouter (verificado 2025)
    models = [
        'deepseek/deepseek-chat-v3-0324:free',
        'deepseek/deepseek-r1:free',
        'meta-llama/llama-3.3-70b-instruct:free',
        'meta-llama/llama-3.1-8b-instruct:free',
        'qwen/qwen-2.5-72b-instruct:free',
        'qwen/qwen-2.5-7b-instruct:free',
        'google/gemini-2.0-flash-exp:free',
        'microsoft/phi-3-medium-128k-instruct:free',
        'nousresearch/hermes-3-llama-3.1-405b:free',
        'mistralai/mistral-7b-instruct:free',
    ]
    errors = []

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            'https://openrouter.ai/api/v1/chat/completions', headers, body)
        if err:
            errors.append(f"{model.split('/')[-1]}: {err[:80]}")
            logger.debug(f"OpenRouter {model}: {err}")
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"OpenRouter OK: {model}")
                return text, None
        except Exception as e:
            errors.append(f"{model.split('/')[-1]}: parse {e}")
            continue

    first = errors[0] if errors else "sem resposta"
    tail  = f' (+{len(errors)-1} mais)' if len(errors) > 1 else ''
    return None, f"OpenRouter: {first}{tail}"

# ── Mistral ───────────────────────────────────────────────────────────────────
def _try_mistral(messages, system):
    key = _get_key('MISTRAL_API_KEY')
    if not key: return None, "MISTRAL_API_KEY não definida"

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs    = [{'role': 'system', 'content': system}] + [
              {'role': m['role'], 'content': m['content']} for m in messages]
    models  = ['mistral-small-latest', 'open-mistral-7b', 'open-mixtral-8x7b']
    errors  = []

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request('https://api.mistral.ai/v1/chat/completions', headers, body)
        if err:
            errors.append(f"{model}: {err}")
            logger.debug(f"Mistral {model}: {err}")
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Mistral OK: {model}")
                return text, None
        except Exception as e:
            errors.append(f"{model}: parse {e}")
            continue

    summary = ' | '.join(errors[:2])
    return None, f"Mistral: {summary}"

# ── Groq (bloqueado por Cloudflare no Render Free) ───────────────────────────
def _try_groq(messages, system):
    key = _get_key('GROQ_API_KEY')
    if not key: return None, "GROQ_API_KEY não definida"

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs    = [{'role': 'system', 'content': system}] + [
              {'role': m['role'], 'content': m['content']} for m in messages]
    # Tenta apenas o modelo mais rápido — falha rápido se Cloudflare bloquear
    models  = ['llama-3.3-70b-versatile', 'llama3-70b-8192', 'llama-3.1-8b-instant']
    errors  = []

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            'https://api.groq.com/openai/v1/chat/completions', headers, body)
        if err:
            errors.append(f"{model}: {err}")
            logger.debug(f"Groq {model}: {err}")
            # Se for erro 1010 (Cloudflare IP block), não vale a pena tentar os outros
            if '1010' in str(err):
                logger.warning("Groq: bloqueado por Cloudflare (erro 1010) — IPs do Render não suportados")
                break
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Groq OK: {model}")
                return text, None
        except Exception as e:
            errors.append(f"{model}: parse {e}")
            continue

    summary = errors[0] if errors else "sem resposta"
    if '1010' in summary:
        return None, "Groq: bloqueado por Cloudflare no Render (erro 1010) — usa Gemini ou OpenRouter"
    return None, f"Groq: {summary}"

# ── Cerebras (bloqueado por Cloudflare no Render Free) ───────────────────────
def _try_cerebras(messages, system):
    key = _get_key('CEREBRAS_API_KEY')
    if not key: return None, "CEREBRAS_API_KEY não definida"

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs    = [{'role': 'system', 'content': system}] + [
              {'role': m['role'], 'content': m['content']} for m in messages]
    models  = ['llama-3.3-70b', 'llama3.1-70b', 'llama3.1-8b']
    errors  = []

    for model in models:
        body   = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request(
            'https://api.cerebras.ai/v1/chat/completions', headers, body)
        if err:
            errors.append(f"{model}: {err}")
            logger.debug(f"Cerebras {model}: {err}")
            if '1010' in str(err):
                logger.warning("Cerebras: bloqueado por Cloudflare (erro 1010)")
                break
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text:
                logger.info(f"Cerebras OK: {model}")
                return text, None
        except Exception as e:
            errors.append(f"{model}: parse {e}")
            continue

    summary = errors[0] if errors else "sem resposta"
    if '1010' in summary:
        return None, "Cerebras: bloqueado por Cloudflare no Render (erro 1010)"
    return None, f"Cerebras: {summary}"

# ── Validação ─────────────────────────────────────────────────────────────────
def validate_api(provider_name):
    t0   = time.time()
    fns  = {'gemini': _try_gemini, 'openrouter': _try_openrouter,
            'mistral': _try_mistral, 'groq': _try_groq, 'cerebras': _try_cerebras}
    name = provider_name.lower()
    fn   = fns.get(name)
    if not fn: return False, f"Provider '{name}' desconhecido", 0

    resp, err = fn([{'role': 'user', 'content': 'Responde só: OK'}], 'Responde só: OK')
    ms = int((time.time() - t0) * 1000)
    ok = bool(resp)
    _last_validation[name] = {'ok': ok, 'status': 'OK' if ok else err, 'ts': time.time(), 'ms': ms}
    return ok, ('OK' if ok else str(err)), ms

def get_validation_status():
    key_map = {
        'gemini':     'GEMINI_API_KEY',
        'openrouter': 'OPENROUTER_API_KEY',
        'mistral':    'MISTRAL_API_KEY',
        'groq':       'GROQ_API_KEY',
        'cerebras':   'CEREBRAS_API_KEY',
    }
    status = {}
    for name, env_var in key_map.items():
        key    = _get_key(env_var)
        cached = _last_validation.get(name, {})
        note   = ''
        if name in ('groq', 'cerebras'):
            note = ' ⚠️ bloqueado Cloudflare no Render'
        status[name] = {
            'key_set':     bool(key),
            'key_prefix':  (key[:12] + '...') if key else 'NOT SET',
            'last_ok':     cached.get('ok'),
            'last_status': cached.get('status', 'não testado') + note,
            'last_ms':     cached.get('ms', 0),
        }
    return status

def get_router_status():
    """Full status dict for the /api/status endpoint."""
    key_map = {
        'gemini':     'GEMINI_API_KEY',
        'openrouter': 'OPENROUTER_API_KEY',
        'mistral':    'MISTRAL_API_KEY',
        'groq':       'GROQ_API_KEY',
        'cerebras':   'CEREBRAS_API_KEY',
    }
    providers = {}
    for name, env_var in key_map.items():
        key    = _get_key(env_var)
        cached = _last_validation.get(name, {})
        note   = ' ⚠️ bloqueado Cloudflare no Render' if name in ('groq', 'cerebras') else ''
        providers[name] = {
            'key_set':        bool(key),
            'key_prefix':     (key[:12] + '...') if key else 'NOT SET',
            'last_ok':        cached.get('ok'),
            'last_status':    cached.get('status', 'não testado') + note,
            'last_ms':        cached.get('ms', 0),
            'last_tested_ts': cached.get('ts'),
            'quota_exceeded': False,
            'quota_reset_in': 0,
        }
    active = [n for n, v in providers.items() if v['key_set']]
    return {
        'providers':        providers,
        'mode':             _last_used_provider,
        'fallback_active':  bool(_last_used_provider and _last_used_provider.lower() not in ('gemini', 'none')),
        'active_providers': active,
        'quota_saver_mode': False,
        'recent_errors':    [],
        'timestamps': {
            'server_time':     time.time(),
            'server_time_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
    }

def reload_and_validate():
    _last_validation.clear()
    results = {}
    for name in ['gemini', 'openrouter', 'mistral']:
        ok, status, ms = validate_api(name)
        results[name] = {'ok': ok, 'status': status, 'ms': ms}
        logger.info(f"reload [{name}]: {'OK' if ok else status}")
    return results

# ── Router principal ───────────────────────────────────────────────────────────
def get_ai_response(messages, memory_context=''):
    """
    Ordem: Mistral → OpenRouter → Gemini → Groq → Cerebras
    Mistral primeiro porque tem chave válida e responde bem.
    Groq/Cerebras estão no fim porque são bloqueados pelo Cloudflare no Render Free.
    Orçamento global de 90s para garantir resposta antes do timeout do gunicorn (120s).
    """
    system    = SYSTEM_PROMPT + (memory_context or '')
    providers = [
        ('Mistral',    _try_mistral),
        ('OpenRouter', _try_openrouter),
        ('Gemini',     _try_gemini),
        ('Groq',       _try_groq),
        ('Cerebras',   _try_cerebras),
    ]
    errors   = []
    deadline = time.time() + 90

    for name, fn in providers:
        if time.time() > deadline:
            logger.warning(f"Router: orçamento de 90s esgotado antes de tentar {name}")
            errors.append(f"{name}: orçamento esgotado")
            break
        try:
            response, err = fn(messages, system)
        except Exception as e:
            err      = f"exception: {e}"
            response = None
            logger.error(f"Router [{name}] exception: {e}")

        if response:
            logger.info(f"AI response via {name} ({len(response)} chars)")
            global _last_used_provider
            _last_used_provider = name
            return response, name

        errors.append(f"{name}: {err}")
        logger.debug(f"Router [{name}] failed: {err}")

    # Todos falharam — analisa os erros e dá diagnóstico acionável
    all_errors_str = ' '.join(errors)
    gemini_quota   = '429' in all_errors_str and ('quota' in all_errors_str.lower() or 'exceeded' in all_errors_str.lower())
    gemini_key     = bool(_get_key('GEMINI_API_KEY'))
    or_key         = bool(_get_key('OPENROUTER_API_KEY'))

    lines = ["⚠️ **Nenhuma IA respondeu agora.**\n"]

    # Diagnóstico específico por causa
    if gemini_quota and gemini_key:
        lines.append(
            "**🔴 Causa principal: Cota Gemini esgotada (HTTP 429)**\n"
            "A cota diária gratuita do Gemini é de ~1500 pedidos/dia por projeto.\n"
            "Quando esgota, todos os modelos do mesmo API key falham.\n\n"
            "**Solução imediata (2 opções):**\n"
            "1. ⏳ **Aguarda** até à meia-noite (hora de Lisboa) — a cota reinicia automaticamente\n"
            "2. 💳 **Ativa faturação** em https://aistudio.google.com → a cota sobe para ~60k/dia "
            "e os primeiros $10/mês são gratuitos (custo real: ~$0.001 por mensagem)\n"
        )

    if not gemini_key:
        lines.append("❌ `GEMINI_API_KEY` não definida no Render → Environment\n")
    if not or_key:
        lines.append("❌ `OPENROUTER_API_KEY` não definida no Render → Environment\n")

    # Resumo dos erros (compacto)
    relevant = [e for e in errors if '1010' not in e and 'Cloudflare' not in e]
    if relevant:
        lines.append("**Erros (resumo):**")
        for e in relevant[:3]:
            lines.append(f"• {e[:100]}")

    lines.append(
        "\n**Enquanto a cota não reinicia:**\n"
        "• Os comandos internos continuam a funcionar (mostra limites, liga xtb, etc.)\n"
        "• Escreve `recarregar ia` depois de corrigir para testar de novo"
    )

    logger.error(f"All providers failed: {errors}")
    return "\n".join(lines), "none"
