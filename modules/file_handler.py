"""File handler — upload e análise de PDFs e outros ficheiros."""
import os, re

def handle_upload(file, user_id, data_dir, ai_fn):
    filename = file.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext == 'pdf':
        return _handle_pdf(file, user_id, data_dir, ai_fn)
    elif ext in ['txt', 'md', 'csv']:
        return _handle_text(file, user_id, ai_fn, ext)
    else:
        return {'error': f'Tipo não suportado: .{ext}. Use PDF, TXT, MD ou CSV'}

def _handle_pdf(file, user_id, data_dir, ai_fn):
    try:
        pdf_bytes = file.read()
        text = _extract_pdf_text(pdf_bytes)
        if not text or len(text) < 50:
            return {'error': 'Não foi possível extrair texto. O PDF pode ser uma imagem.'}

        # Guarda no disco se disponível
        upload_dir = os.path.join(data_dir, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        save_path = os.path.join(upload_dir, f"user_{user_id}_{file.filename}")
        with open(save_path, 'wb') as f:
            f.write(pdf_bytes)

        # Analisa com IA
        prompt = f"Analisa este documento e resume os pontos principais:\n\n{text[:4000]}"
        messages = [{'role': 'user', 'content': prompt}]
        response, model = ai_fn(messages, '')

        return {'ok': True, 'filename': file.filename, 'chars': len(text),
                'analysis': response, 'model': model}
    except Exception as e:
        return {'error': str(e)[:200]}

def _handle_text(file, user_id, ai_fn, ext):
    try:
        content = file.read().decode('utf-8', errors='ignore')
        prompt = f"Analisa este ficheiro {ext.upper()} e resume o conteúdo:\n\n{content[:4000]}"
        messages = [{'role': 'user', 'content': prompt}]
        response, model = ai_fn(messages, '')
        return {'ok': True, 'chars': len(content), 'analysis': response, 'model': model}
    except Exception as e:
        return {'error': str(e)[:200]}

def _extract_pdf_text(pdf_bytes):
    """Extrai texto de PDF sem dependências externas."""
    try:
        text = pdf_bytes.decode('latin-1', errors='ignore')
        # Tenta extrair texto entre BT e ET
        chunks = re.findall(r'BT(.*?)ET', text, re.DOTALL)
        words = []
        for chunk in chunks:
            strings = re.findall(r'\(([^)]{1,200})\)', chunk)
            words.extend(strings)
        result = ' '.join(words).strip()
        if len(result) < 100:
            # Fallback: texto ASCII legível
            result = re.sub(r'[^\x20-\x7E\n]', ' ', text)
            result = re.sub(r'\s+', ' ', result)[:5000]
        return result.strip()
    except Exception:
        return None
