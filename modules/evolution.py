"""
NEXUS Self-Evolution Module — Autonomia de código e sistema
A NEXUS gera, corrige e sugere código sem depender de ferramentas externas.
Toda alteração em produção requer autorização nível 3.
"""
import os, json, zipfile, tempfile, datetime, logging
logger = logging.getLogger('nexus.evolution')


def generate_code(task_description, language, context, ai_fn):
    """
    Gera código para uma tarefa específica.
    Nível 1 — sem autorização (só geração, não aplica).
    """
    prompt = f"""Gera código {language} para a seguinte tarefa:

TAREFA: {task_description}

CONTEXTO DO SISTEMA: {context[:500] if context else 'NEXUS IA Pessoal - Flask + Python'}

Requisitos:
- Código limpo e bem comentado
- Tratamento de erros
- Seguro (sem hardcode de credenciais)
- Compatível com a arquitetura existente (Flask, SQLite, módulos Python)

Responde APENAS com o código, sem explicações desnecessárias.
No início coloca um comentário com: o que faz, porque é necessário, riscos."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {
        'code': response,
        'language': language,
        'task': task_description,
        'model': model,
        'status': 'GENERATED — não aplicado. Requer autorização para produção.'
    }


def analyze_and_fix(file_content, error_message, ai_fn):
    """Analisa um ficheiro com erro e sugere correção."""
    prompt = f"""Analisa este código com erro e sugere a correção:

ERRO:
{error_message[:500]}

CÓDIGO:
{file_content[:3000]}

Responde com:
1. CAUSA DO ERRO (1 linha)
2. SOLUÇÃO (código corrigido completo)
3. EXPLICAÇÃO (o que mudou e porquê)
4. RISCOS (existe algum risco na correção?)"""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'analysis': response, 'model': model}


def suggest_improvements(module_name, module_content, ai_fn):
    """Sugere melhorias para um módulo existente."""
    prompt = f"""Analisa este módulo Python e sugere melhorias:

MÓDULO: {module_name}

CÓDIGO:
{module_content[:3000]}

Sugere:
1. MELHORIAS DE PERFORMANCE (se aplicável)
2. MELHORIAS DE SEGURANÇA (obrigatório verificar)
3. NOVAS FUNCIONALIDADES ÚTEIS
4. CÓDIGO DE EXEMPLO para cada melhoria
5. PRIORIDADE (alta/média/baixa) e ESFORÇO (horas)

Foca no que trará mais valor ao utilizador."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'suggestions': response, 'module': module_name, 'model': model}


def create_update_zip(files_dict, version=None):
    """
    Cria um ZIP de atualização com os ficheiros fornecidos.
    files_dict: {'path/to/file.py': 'content string', ...}
    Requer autorização nível 3 para aplicar em produção.
    """
    version = version or datetime.datetime.now().strftime('%Y%m%d_%H%M')
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f'_nexus_update_{version}.zip')
    tmp.close()

    try:
        with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filepath, content in files_dict.items():
                zf.writestr(filepath, content)
        logger.info(f"Update ZIP criado: {tmp.name} ({len(files_dict)} ficheiros)")
        return tmp.name, None
    except Exception as e:
        return None, str(e)


def list_modules(base_path=None):
    """Lista módulos existentes do sistema."""
    base_path = base_path or os.path.join(os.path.dirname(__file__))
    modules = {}
    try:
        for fname in os.listdir(base_path):
            if fname.endswith('.py') and not fname.startswith('_'):
                fpath = os.path.join(base_path, fname)
                with open(fpath, 'r') as f:
                    content = f.read()
                # Extrai docstring
                lines = content.split('\n')
                doc = ''
                if lines and lines[0].startswith('"""'):
                    for line in lines[1:]:
                        if '"""' in line:
                            break
                        doc += line.strip() + ' '
                modules[fname] = {
                    'lines': len(lines),
                    'description': doc.strip()[:100],
                    'path': fpath
                }
    except Exception as e:
        logger.error(f"List modules: {e}")
    return modules


def read_module(module_name, base_path=None):
    """Lê o conteúdo de um módulo."""
    base_path = base_path or os.path.dirname(__file__)
    fpath = os.path.join(base_path, module_name)
    if not os.path.exists(fpath):
        return None, f"Módulo não encontrado: {module_name}"
    try:
        with open(fpath, 'r') as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)


def generate_new_module(module_name, description, requirements, ai_fn):
    """
    Gera código para um novo módulo completo.
    Não aplica — só gera para revisão.
    """
    prompt = f"""Cria um módulo Python completo para a NEXUS IA:

NOME: {module_name}
DESCRIÇÃO: {description}
REQUISITOS: {requirements}

ARQUITETURA EXISTENTE:
- Flask backend com SQLite
- Módulos em /modules/*.py
- Endpoints em app.py
- Variáveis de ambiente para credenciais

O módulo deve:
- Ter docstring completo no topo
- Ter logging adequado
- Ter tratamento de erros em todas as funções
- Ser seguro (sem credenciais hardcoded)
- Ser compatível com a arquitetura existente

Inclui também os endpoints Flask necessários para integrar no app.py."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {
        'module_name': module_name,
        'code': response,
        'model': model,
        'status': 'GENERATED — requer revisão e autorização para aplicar'
    }
