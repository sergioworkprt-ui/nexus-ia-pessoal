from modules.database import get_db
"""
NEXUS Learning Module — Aprendizagem contínua e evolução
A NEXUS aprende com histórico, sugere melhorias e evolui com autorização.
"""
import json, datetime, logging, sqlite3
logger = logging.getLogger('nexus.learning')


def analyze_conversation_patterns(user_id, db_path, ai_fn):
    """Analisa padrões nas conversas e sugere melhorias."""
    try:
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row

        # Últimas 50 mensagens do utilizador
        msgs = conn.execute(
            "SELECT content, created_at FROM conversations WHERE user_id=? AND role='user' ORDER BY id DESC LIMIT 50",
            (user_id,)
        ).fetchall()

        # Tarefas concluídas e falhadas
        tasks = conn.execute(
            "SELECT title, status, result FROM tasks WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()

        conn.close()

        if not msgs:
            return {'suggestions': [], 'patterns': [], 'insights': 'Sem histórico suficiente'}

        # Prepara contexto para análise
        msg_texts = [m['content'][:100] for m in msgs[:20]]
        task_summary = [(t['title'], t['status']) for t in tasks]

        prompt = f"""Analisa os padrões de uso da NEXUS por este utilizador:

MENSAGENS RECENTES (amostra):
{json.dumps(msg_texts, ensure_ascii=False, indent=2)}

TAREFAS:
{json.dumps(task_summary, ensure_ascii=False, indent=2)}

Com base nisto, identifica:
1. **PADRÕES**: O que o utilizador mais faz/pede
2. **PONTOS FORTES**: O que está a funcionar bem
3. **MELHORIAS SUGERIDAS**: 3 melhorias concretas para a NEXUS
4. **PRÓXIMAS FUNCIONALIDADES**: O que seria mais útil implementar
5. **INSIGHTS**: Observações sobre os objetivos do utilizador

Responde de forma concisa e orientada a ação."""

        messages = [{'role': 'user', 'content': prompt}]
        response, model = ai_fn(messages, '')

        # Guarda sugestões
        save_learning_insight(user_id, db_path, 'pattern_analysis', response)

        return {
            'analysis': response,
            'model': model,
            'messages_analyzed': len(msgs),
            'tasks_analyzed': len(tasks)
        }
    except Exception as e:
        logger.error(f"Pattern analysis error: {e}")
        return {'error': str(e)}


def save_learning_insight(user_id, db_path, insight_type, content):
    """Guarda um insight de aprendizagem."""
    try:
        conn = get_db(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_insights (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                type TEXT,
                content TEXT,
                applied INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT INTO learning_insights (user_id, type, content) VALUES (?, ?, ?)",
            (user_id, insight_type, content[:2000])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Save insight error: {e}")


def get_learning_history(user_id, db_path):
    """Retorna histórico de aprendizagem."""
    try:
        conn = get_db(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM learning_insights WHERE user_id=? ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def compare_sources(sources, ai_fn):
    """
    Fact-check e comparação de múltiplas fontes.
    Identifica exageros, contradições e oportunidades reais.
    """
    if not sources:
        return {'error': 'Sem fontes para comparar'}

    sources_text = '\n\n'.join([f"FONTE {i+1}:\n{s[:1000]}" for i, s in enumerate(sources)])

    prompt = f"""Compara estas {len(sources)} fontes e faz um fact-check completo:

{sources_text}

Analisa:
1. **CONSENSO**: O que todas as fontes concordam
2. **CONTRADIÇÕES**: Onde as fontes divergem
3. **EXAGEROS**: Afirmações exageradas ou impossíveis
4. **RISCOS ESCONDIDOS**: O que não foi mencionado mas é importante
5. **OPORTUNIDADES REAIS**: O que de facto é possível e realista
6. **VEREDICTO FINAL**: O que deve o utilizador acreditar e fazer

Sê crítico, objetivo e protege o utilizador de desinformação."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'comparison': response, 'model': model, 'sources_count': len(sources)}


def generate_improvement_plan(user_id, db_path, ai_fn):
    """Gera um plano de melhorias para a NEXUS com base no histórico."""
    insights = get_learning_history(user_id, db_path)
    insights_text = '\n'.join([f"- {i['type']}: {i['content'][:200]}" for i in insights[:5]])

    prompt = f"""Com base no histórico de aprendizagem da NEXUS:

{insights_text if insights_text else 'Sem histórico ainda — análise baseada em capacidades atuais'}

Cria um plano de melhoria com:
1. **MELHORIAS IMEDIATAS** (que posso implementar agora)
2. **MELHORIAS A MÉDIO PRAZO** (próximo mês)
3. **MELHORIAS FUTURAS** (quando houver orçamento)
4. **COMO IMPLEMENTAR CADA UMA** (passos concretos)
5. **PRIORIDADE** (o que trará mais valor primeiro)

Cada melhoria deve indicar: custo (€0 ou custo), tempo de implementação, impacto esperado."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    save_learning_insight(user_id, db_path, 'improvement_plan', response)
    return {'plan': response, 'model': model}


def investment_education(topic, level, ai_fn):
    """Módulo educativo de investimento."""
    levels = {
        'beginner': 'sou completamente iniciante, sem experiência em investimentos',
        'intermediate': 'tenho alguma experiência básica em investimentos',
        'advanced': 'tenho experiência e quero aprofundar o tema'
    }
    user_level = levels.get(level, levels['beginner'])

    prompt = f"""Cria um módulo educativo sobre: "{topic}"

O utilizador diz: {user_level}

Inclui:
1. **EXPLICAÇÃO SIMPLES**: O que é e como funciona
2. **RISCOS REAIS**: Lista todos os riscos (não suavizes)
3. **RETORNO REALISTA**: O que é realmente possível ganhar (sem exageros)
4. **PLANO PASSO A PASSO**: Como começar com segurança (começando por 10€)
5. **ERROS COMUNS**: O que os iniciantes fazem de errado
6. **SIMULAÇÃO**: Exemplo prático com valores reais
7. **RECURSOS GRATUITOS**: Onde aprender mais

Tom: educativo, honesto, sem promessas falsas. Protege o utilizador."""

    messages = [{'role': 'user', 'content': prompt}]
    response, model = ai_fn(messages, '')
    return {'education': response, 'model': model, 'topic': topic, 'level': level}
