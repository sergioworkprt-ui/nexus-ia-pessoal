"""
NEXUS Chat Commands Engine
Controlo total da NEXUS via chat natural.
Interpreta comandos e executa ações com autorização obrigatória.
"""
import re, json, logging, datetime
logger = logging.getLogger('nexus.commands')

# Frase de autorização obrigatória para ações críticas
AUTH_PHRASE = 'SIM, AUTORIZO'

# Níveis de risco dos comandos
RISK_LEVELS = {
    'info': 1,      # só leitura
    'config': 2,    # altera configuração
    'critical': 3,  # ação financeira/sistema
}

# Padrões de comandos
COMMAND_PATTERNS = [
    # Limites financeiros
    (r'define?\s+limite\s+di[aá]rio\s+(?:para\s+)?(\d+(?:\.\d+)?)\s*€?', 'set_daily_limit', RISK_LEVELS['config']),
    (r'altera?\s+limite\s+de?\s+perda\s+(?:para\s+)?(\d+(?:\.\d+)?)\s*%?', 'set_loss_limit', RISK_LEVELS['config']),
    (r'define?\s+limite\s+(?:por\s+)?opera[çc][aã]o\s+(?:para\s+)?(\d+(?:\.\d+)?)\s*€?', 'set_op_limit', RISK_LEVELS['config']),

    # Modos
    (r'ativa?\s+modo\s+seguro', 'enable_safe_mode', RISK_LEVELS['config']),
    (r'desativa?\s+modo\s+seguro', 'disable_safe_mode', RISK_LEVELS['config']),
    (r'muda?\s+(?:para\s+)?modo\s+demo', 'set_mode_demo', RISK_LEVELS['critical']),
    (r'muda?\s+(?:para\s+)?modo\s+real', 'set_mode_real', RISK_LEVELS['critical']),

    # Estado e info
    (r'mostra?\s+limites?\s+atuais?', 'show_limits', RISK_LEVELS['info']),
    (r'mostra?\s+estado\s+(?:do\s+)?m[oó]dulo\s+10', 'show_mod10', RISK_LEVELS['info']),
    (r'mostra?\s+estado\s+(?:da\s+)?nexus', 'show_nexus_status', RISK_LEVELS['info']),
    (r'mostra?\s+portfolio', 'show_portfolio', RISK_LEVELS['info']),
    (r'mostra?\s+alertas?', 'show_alerts', RISK_LEVELS['info']),
    (r'mostra?\s+tarefas?', 'show_tasks', RISK_LEVELS['info']),
    (r'mostra?\s+logs?', 'show_logs', RISK_LEVELS['info']),

    # Monitor
    (r'ativa?\s+monitor\s+24[/\s]?7?', 'enable_monitor', RISK_LEVELS['config']),
    (r'desativa?\s+monitor', 'disable_monitor', RISK_LEVELS['config']),
    (r'adiciona?\s+ativo\s+([\w]+)\s+(?:ao\s+)?monitor', 'add_asset_monitor', RISK_LEVELS['config']),
    (r'verifica?\s+(?:o\s+)?ativo\s+([\w]+)', 'check_asset_price', RISK_LEVELS['info']),

    # Tarefas agendadas
    (r'cria?\s+tarefa\s+(?:autom[aá]tica\s+)?[àa]s?\s+(\d{1,2}[:\s]\d{2})\s+(?:para\s+)?(.+)', 'create_scheduled_task', RISK_LEVELS['config']),

    # XTB
    (r'liga\s+xtb', 'connect_xtb', RISK_LEVELS['config']),
    (r'desliga\s+xtb', 'disconnect_xtb', RISK_LEVELS['config']),
    (r'mostra?\s+(?:saldo|conta|posi[çc][oõ]es?)\s+xtb', 'show_xtb_account', RISK_LEVELS['config']),

    # Módulo 10 / Auto-evolução
    (r'aprende?\s+com\s+(?:os\s+)?logs?\s+(?:de\s+)?hoje', 'learn_from_logs', RISK_LEVELS['config']),
    (r'melhora?\s+(?:o\s+)?m[oó]dulo\s+([\w]+)', 'improve_module', RISK_LEVELS['config']),
    (r'gera?\s+patch\s+(?:para\s+)?(.+)', 'generate_patch', RISK_LEVELS['config']),
    (r'evolui?\s+(?:para\s+)?(?:vers[aã]o\s+)?([\d.]+)', 'evolve_version', RISK_LEVELS['critical']),
    (r'analisa?\s+c[oó]digo', 'analyze_code', RISK_LEVELS['config']),

    # Emergência
    (r'para\s+tudo|emergência|emergency\s+stop', 'emergency_stop', RISK_LEVELS['critical']),
    (r'retoma?\s+opera[çc][oõ]es?', 'emergency_resume', RISK_LEVELS['critical']),
]


def parse_command(message):
    """
    Tenta identificar um comando na mensagem.
    Retorna: (command_name, args, risk_level) ou None
    """
    msg = message.lower().strip()

    for pattern, command, risk in COMMAND_PATTERNS:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            args = list(m.groups()) if m.groups() else []
            logger.info(f"Comando detetado: {command} args={args} risk={risk}")
            return command, args, risk

    return None, None, None


def needs_authorization(risk_level):
    """Comandos de risco 2+ precisam de 'SIM, AUTORIZO'."""
    return risk_level >= RISK_LEVELS['config']


def check_authorization(message, pending_command):
    """Verifica se a mensagem é uma autorização para o comando pendente."""
    return AUTH_PHRASE.upper() in message.upper() and pending_command is not None


def format_command_response(command, args, risk_level, needs_auth):
    """Formata resposta para um comando detetado."""
    descriptions = {
        'set_daily_limit': f"Definir limite diário para **{args[0] if args else '?'}€**",
        'set_loss_limit': f"Alterar limite de perda para **{args[0] if args else '?'}%**",
        'set_op_limit': f"Definir limite por operação para **{args[0] if args else '?'}€**",
        'enable_safe_mode': "Ativar **modo seguro** (sem ordens automáticas)",
        'disable_safe_mode': "Desativar modo seguro",
        'set_mode_demo': "Mudar XTB para **modo DEMO**",
        'set_mode_real': "Mudar XTB para **modo REAL** ⚠️",
        'show_limits': "Mostrar limites atuais",
        'show_mod10': "Mostrar estado do Módulo 10",
        'show_nexus_status': "Mostrar estado completo da NEXUS",
        'enable_monitor': "Ativar monitor 24/7",
        'disable_monitor': "Desativar monitor",
        'add_asset_monitor': f"Adicionar **{args[0] if args else '?'}** ao monitor",
        'check_asset_price': f"Verificar preço de **{args[0] if args else '?'}**",
        'create_scheduled_task': f"Criar tarefa às **{args[0] if args else '?'}**: {args[1] if len(args)>1 else ''}",
        'connect_xtb': "Ligar ao XTB",
        'disconnect_xtb': "Desligar do XTB",
        'show_xtb_account': "Mostrar conta/posições XTB",
        'learn_from_logs': "Iniciar ciclo de aprendizagem com logs de hoje",
        'improve_module': f"Melhorar módulo **{args[0] if args else '?'}**",
        'generate_patch': f"Gerar patch para: *{args[0] if args else '?'}*",
        'evolve_version': f"Evoluir para versão **{args[0] if args else '?'}**",
        'analyze_code': "Analisar saúde do código",
        'emergency_stop': "🛑 **TRAVÃO DE EMERGÊNCIA**",
        'emergency_resume': "▶ Retomar operações",
    }

    desc = descriptions.get(command, command)
    risk_labels = {1: '🟢 Nível 1', 2: '🟡 Nível 2', 3: '🔴 Nível 3'}

    if not needs_auth:
        return f"⚡ **Comando:** {desc}\n{risk_labels.get(risk_level, '')} — A executar automaticamente..."

    return (
        f"⚡ **Comando detetado:** {desc}\n"
        f"{risk_labels.get(risk_level, '')} — Requer autorização\n\n"
        f"Para confirmar, escreve: **{AUTH_PHRASE}**\n"
        f"Para cancelar, escreve: **NÃO**"
    )


async def execute_command(command, args, user_id, db_path, session_data,
                          get_ai_fn, send_email_fn):
    """
    Executa o comando identificado.
    Retorna: resposta em texto para o utilizador.
    """
    import os

    try:
        if command == 'show_limits':
            from modules.financial import get_financial_config
            from modules.market_monitor import get_monitor_config
            fin = get_financial_config(user_id, db_path)
            mon = get_monitor_config(user_id, db_path)
            return (
                f"📊 **Limites atuais:**\n\n"
                f"**Financeiros:**\n"
                f"• Perda máxima / operação: {fin.get('max_loss_per_trade', 5)}€\n"
                f"• Meta de lucro: {fin.get('profit_target', 20)}€\n"
                f"• Reinvestimento: {fin.get('reinvest_amount', 10)}€\n"
                f"• Retirada: {int(fin.get('withdraw_percent', 0.5)*100)}% dos lucros\n\n"
                f"**Monitor:**\n"
                f"• Alerta queda: -{mon.get('drop_alert_pct', 2)}%\n"
                f"• Alerta subida: +{mon.get('rise_alert_pct', 3)}%\n"
                f"• Perda máx. diária: {mon.get('max_loss_per_day', 15)}€\n"
                f"• Valor máx. / op: {mon.get('max_amount_per_op', 10)}€\n"
                f"• Modo: {mon.get('mode', 'ask').upper()}"
            )

        elif command == 'set_daily_limit':
            from modules.market_monitor import get_monitor_config, save_monitor_config
            val = float(args[0]) if args else 15.0
            config = get_monitor_config(user_id, db_path)
            config['max_loss_per_day'] = val
            save_monitor_config(user_id, db_path, config)
            return f"✅ Limite diário definido para **{val}€**"

        elif command == 'set_loss_limit':
            from modules.financial import get_financial_config, save_financial_config
            val = float(args[0]) if args else 5.0
            config = get_financial_config(user_id, db_path)
            config['max_loss_per_trade'] = val
            save_financial_config(user_id, db_path, config)
            return f"✅ Limite de perda por operação definido para **{val}€**"

        elif command == 'set_op_limit':
            from modules.market_monitor import get_monitor_config, save_monitor_config
            val = float(args[0]) if args else 10.0
            config = get_monitor_config(user_id, db_path)
            config['max_amount_per_op'] = val
            save_monitor_config(user_id, db_path, config)
            return f"✅ Limite por operação definido para **{val}€**"

        elif command == 'enable_safe_mode':
            from modules.market_monitor import get_monitor_config, save_monitor_config, MODE_ASK
            config = get_monitor_config(user_id, db_path)
            config['mode'] = MODE_ASK
            save_monitor_config(user_id, db_path, config)
            return "🛡️ **Modo seguro ativado** — NEXUS pergunta antes de agir"

        elif command == 'disable_safe_mode':
            from modules.market_monitor import get_monitor_config, save_monitor_config, MODE_AUTO
            config = get_monitor_config(user_id, db_path)
            config['mode'] = MODE_AUTO
            save_monitor_config(user_id, db_path, config)
            return "⚡ **Modo auto ativado** — NEXUS age dentro dos limites"

        elif command == 'set_mode_demo':
            from modules.mod10 import save_state
            save_state(db_path, 'xtb_mode_override', 'demo')
            os.environ['XTB_MODE'] = 'demo'
            return "🟡 XTB alterado para **modo DEMO** — sem ordens reais"

        elif command == 'set_mode_real':
            from modules.mod10 import save_state
            save_state(db_path, 'xtb_mode_override', 'real')
            os.environ['XTB_MODE'] = 'real'
            return "🔴 XTB alterado para **modo REAL** — ordens reais ativas!"

        elif command == 'show_nexus_status':
            from modules.mod10 import mod10, load_state
            from modules.market_monitor import market_monitor, get_monitor_config
            mon_config = get_monitor_config(user_id, db_path)
            mod10_state = mod10.get_status(db_path)
            return (
                f"🤖 **Estado da NEXUS:**\n\n"
                f"• Módulo 10: {'🟢 Ativo' if mod10_state['running'] else '🔴 Parado'}\n"
                f"• Monitor 24/7: {'🟢 Ativo' if market_monitor.is_running() else '🔴 Parado'}\n"
                f"• Modo decisão: {mon_config.get('mode','ask').upper()}\n"
                f"• XTB Modo: {os.environ.get('XTB_MODE','demo').upper()}\n"
                f"• Ciclos Mod10: {mod10_state.get('cycles_total',0)}\n"
                f"• Patches pendentes: {mod10_state.get('pending_patches',0)}"
            )

        elif command == 'show_mod10':
            from modules.mod10 import mod10
            s = mod10.get_status(db_path)
            return (
                f"🤖 **Módulo 10:**\n"
                f"• Estado: {'🟢 Ativo' if s['running'] else '🔴 Parado'}\n"
                f"• Ciclos: {s.get('cycles_total',0)}\n"
                f"• Último ciclo: {s.get('last_cycle','nunca')[:16]}\n"
                f"• Patches pendentes: {s.get('pending_patches',0)}\n"
                f"• Última aprendizagem: {s.get('last_learning','nunca')[:16]}"
            )

        elif command == 'enable_monitor':
            return "📡 Monitor 24/7 já está ativo. Verifica em Dashboard → Monitor."

        elif command == 'check_asset_price':
            from modules.market_monitor import get_asset_price
            symbol = args[0].upper() if args else 'SPY'
            price_data, err = get_asset_price(symbol)
            if err: return f"❌ Erro ao obter preço de {symbol}: {err}"
            change = price_data.get('change_pct', 0)
            color_word = "subiu" if change >= 0 else "caiu"
            return (
                f"💹 **{symbol}**: {price_data.get('price',0)} {price_data.get('currency','')}\n"
                f"• Variação: {color_word} {abs(change):.2f}% hoje\n"
                f"• Mercado: {price_data.get('market_state','?')}"
            )

        elif command == 'add_asset_monitor':
            from modules.market_monitor import market_monitor
            symbol = args[0].upper() if args else ''
            if not symbol: return "❌ Símbolo em falta"
            market_monitor.add_asset(user_id, db_path, symbol)
            return f"✅ **{symbol}** adicionado ao monitor 24/7"

        elif command == 'create_scheduled_task':
            time_str = args[0] if args else '08:00'
            task_desc = args[1] if len(args) > 1 else 'Análise automática'
            # Parse time
            time_clean = time_str.replace(' ', ':')
            now = datetime.datetime.now()
            try:
                h, m = map(int, time_clean.split(':'))
                run_at = now.replace(hour=h, minute=m, second=0)
                if run_at <= now:
                    run_at += datetime.timedelta(days=1)
            except Exception:
                run_at = now + datetime.timedelta(hours=1)

            import sqlite3
            conn = sqlite3.connect(db_path)
            import json as _json
            conn.execute(
                "INSERT INTO tasks (user_id, title, description, status, run_at) VALUES (?,?,?,?,?)",
                (user_id, f"Auto: {task_desc[:50]}", _json.dumps({'prompt': task_desc}),
                 'scheduled', run_at.isoformat())
            )
            conn.commit()
            conn.close()
            return f"⏰ Tarefa criada para **{run_at.strftime('%d/%m %H:%M')}**: {task_desc[:80]}"

        elif command == 'show_xtb_account':
            return "💼 Para ver a conta XTB, vai ao menu **📈 XTB** → 'Ver Saldo'. Requer PIN."

        elif command == 'learn_from_logs':
            from modules.mod10 import learn_from_logs as _learn
            result = _learn(db_path, user_id, get_ai_fn)
            if result.get('learned'):
                return f"🧠 **Aprendizagem concluída:**\n\n{result.get('insight','')[:500]}"
            return f"⚠️ {result.get('reason', result.get('error', 'Sem dados'))}"

        elif command == 'improve_module':
            module = args[0] if args else 'xtb'
            from modules.evolution import read_module, suggest_improvements
            content, err = read_module(f"{module}.py")
            if err: return f"❌ Módulo não encontrado: {module}.py"
            result = suggest_improvements(f"{module}.py", content, get_ai_fn)
            return f"💡 **Sugestões para {module}.py:**\n\n{result.get('suggestions','')[:800]}"

        elif command == 'generate_patch':
            issue = args[0] if args else 'otimização geral'
            from modules.mod10 import generate_self_patch
            patch = generate_self_patch(issue, get_ai_fn, db_path)
            return (
                f"🔧 **Patch gerado** #{patch.get('hash','?')}:\n\n"
                f"{patch.get('patch','')[:600]}\n\n"
                f"Para aprovar: vai a **🤖 Mod 10** → Patches Pendentes"
            )

        elif command == 'analyze_code':
            from modules.mod10 import analyze_codebase_health
            result = analyze_codebase_health(get_ai_fn)
            return f"🏥 **Análise do código:**\n\n{result.get('analysis','')[:600]}"

        elif command == 'emergency_stop':
            from modules.security import emergency_stop as sec_stop
            sec_stop(user_id, db_path)
            return "🛑 **TRAVÃO DE EMERGÊNCIA ATIVADO**\nTodas as ações reais foram paradas."

        elif command == 'emergency_resume':
            from modules.security import emergency_resume as sec_resume
            sec_resume(user_id, db_path)
            return "▶ **Sistema retomado** — operações normais restabelecidas."

        else:
            return f"⚠️ Comando '{command}' reconhecido mas não implementado ainda."

    except Exception as e:
        logger.error(f"Execute command error [{command}]: {e}")
        return f"❌ Erro ao executar '{command}': {str(e)[:200]}"
