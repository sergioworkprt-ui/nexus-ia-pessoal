"""AI Router — tenta cada IA gratuita por ordem de qualidade."""
import os, json, urllib.request, urllib.error

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

def _make_request(url, headers, body, timeout=45):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8')), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}"
    except Exception as e:
        return None, str(e)[:150]

def _try_gemini(messages, system):
    key = os.environ.get('GEMINI_API_KEY', '')
    if not key: return None, "GEMINI_API_KEY não definida"
    contents = [{'role': 'user' if m['role']=='user' else 'model',
                 'parts': [{'text': m['content']}]} for m in messages]
    for model_name in ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
        body = {
            'system_instruction': {'parts': [{'text': system}]},
            'contents': contents,
            'generationConfig': {'maxOutputTokens': 4096, 'temperature': 0.7}
        }
        result, err = _make_request(url, {'Content-Type': 'application/json'}, body)
        if err:
            if '503' in str(err) or '429' in str(err) or '404' in str(err):
                continue
            return None, f"Gemini: {err}"
        try:
            text = result['candidates'][0]['content']['parts'][0]['text']
            if text: return text, None
        except: continue
    return None, "Gemini: todos os modelos indisponíveis"

def _try_groq(messages, system):
    key = os.environ.get('GROQ_API_KEY', '')
    if not key: return None, "GROQ_API_KEY não definida"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs = [{'role': 'system', 'content': system}] + messages
    # Try multiple Groq models in case one is unavailable
    for model in ['llama-3.3-70b-versatile', 'llama3-70b-8192', 'llama3-8b-8192', 'gemma2-9b-it']:
        body = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request("https://api.groq.com/openai/v1/chat/completions", headers, body)
        if err:
            if '403' in str(err) or '401' in str(err):
                return None, f"Groq: chave inválida (403)"
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text: return text, None
        except: continue
    return None, "Groq: todos os modelos falharam"

def _try_cerebras(messages, system):
    key = os.environ.get('CEREBRAS_API_KEY', '')
    if not key: return None, "CEREBRAS_API_KEY não definida"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs = [{'role': 'system', 'content': system}] + messages
    for model in ['llama-3.3-70b', 'llama3.1-70b', 'llama3.1-8b']:
        body = {'model': model, 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
        result, err = _make_request("https://api.cerebras.ai/v1/chat/completions", headers, body)
        if err:
            if '403' in str(err) or '401' in str(err):
                return None, f"Cerebras: chave inválida (403)"
            continue
        try:
            text = result['choices'][0]['message']['content']
            if text: return text, None
        except: continue
    return None, "Cerebras: todos os modelos falharam"

def _try_openrouter(messages, system):
    key = os.environ.get('OPENROUTER_API_KEY', '')
    if not key: return None, "OPENROUTER_API_KEY não definida"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {key}',
        'HTTP-Referer': 'https://nexus-ia-pessoal.onrender.com',
        'X-Title': 'NEXUS IA Pessoal'
    }
    msgs = [{'role': 'system', 'content': system}] + messages
    for model in ['google/gemini-flash-1.5', 'meta-llama/llama-3.3-70b-instruct:free',
                  'mistralai/mistral-7b-instruct:free']:
        body = {'model': model, 'messages': msgs, 'max_tokens': 4096}
        result, err = _make_request("https://openrouter.ai/api/v1/chat/completions", headers, body)
        if not err:
            try:
                text = result['choices'][0]['message']['content']
                if text: return text, None
            except: continue
    return None, "OpenRouter: todos os modelos falharam"

def _try_mistral(messages, system):
    key = os.environ.get('MISTRAL_API_KEY', '')
    if not key: return None, "MISTRAL_API_KEY não definida"
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
    msgs = [{'role': 'system', 'content': system}] + messages
    body = {'model': 'mistral-small-latest', 'messages': msgs, 'max_tokens': 4096, 'temperature': 0.7}
    result, err = _make_request("https://api.mistral.ai/v1/chat/completions", headers, body)
    if err: return None, f"Mistral: {err}"
    try: return result['choices'][0]['message']['content'], None
    except: return None, "Mistral: parse error"

def get_ai_response(messages, memory_context=''):
    """Router principal — tenta cada IA por ordem."""
    system = SYSTEM_PROMPT + (memory_context or '')
    providers = [
        ('Gemini 2.5 Flash', _try_gemini),
        ('Groq Llama 3', _try_groq),
        ('Cerebras Llama 3.3', _try_cerebras),
        ('OpenRouter', _try_openrouter),
        ('Mistral', _try_mistral),
    ]
    errors = []
    for name, fn in providers:
        response, err = fn(messages, system)
        if response:
            return response, name
        errors.append(f"{name}: {err}")

    msg = "⚠️ Nenhuma IA disponível.\n\nErros:\n" + "\n".join(errors[:3])
    msg += "\n\nVerifica as API Keys no Render → Environment."
    return msg, "none"
