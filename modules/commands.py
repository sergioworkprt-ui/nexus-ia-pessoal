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

    # IA reload e status
    (r'recarre[gq]a[r]?\s+ia', 'reload_ia', RISK_LEVELS['config']),
    (r'status\s+ia', 'status_ia', RISK_LEVELS['info']),
    (r'diagn[oó]stico\s+ia', 'status_ia', RISK_LEVELS['info']),
    (r'testa[r]?\s+ia', 'status_ia', RISK_LEVELS['info']),
    (r'valida[r]?\s+(?:as\s+)?apis?', 'status_ia', RISK_LEVELS['info']),

    # XTB sessão (aliases naturais)
    (r'inicia[r]?\s+sess[aã]o\s+xtb', 'connect_xtb', RISK_LEVELS['config']),
    (r'inicia[r]?\s+sess[aã]o', 'connect_xtb', RISK_LEVELS['config']),
    (r'conecta[r]?\s+(?:ao\s+)?xtb', 'connect_xtb', RISK_LEVELS['config']),
    (r'login\s+xtb', 'connect_xtb', RISK_LEVELS['config']),
    (r'ativa[r]?\s+xtb', 'connect_xtb', RISK_LEVELS['config']),
    (r'ver\s+(?:saldo|conta|balance)', 'show_xtb_account', RISK_LEVELS['config']),
    (r'ver\s+posi[çc][oõ]es?', 'show_xtb_account', RISK_LEVELS['config']),

    # Monitor aliases
    (r'verifica[r]?\s+(?:o\s+)?mercado', 'enable_monitor', RISK_LEVELS['config']),
    (r'monitoriza[r]?\s+(.+)', 'add_asset_monitor', RISK_LEVELS['config']),

    # Estado aliases
    (r'como\s+est[aá]s?', 'show_nexus_status', RISK_LEVELS['info']),
    (r'estado\s+(?:geral|do\s+sistema)', 'show_nexus_status', RISK_LEVELS['info']),

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
        'reload_ia': "Recarregar e revalidar todas as APIs de IA",
        'status_ia': "Mostrar estado real de todas as APIs de IA",
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


def execute_command(command, args, user_id, db_path, session_data,
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
            conn = sqlite3.connect(db_path, timeout=30)
            import json as _json
            conn.execute(
                "INSERT INTO tasks (user_id, title, description, status, run_at) VALUES (?,?,?,?,?)",
                (user_id, f"Auto: {task_desc[:50]}", _json.dumps({'prompt': task_desc}),
                 'scheduled', run_at.isoformat())
            )
            conn.commit()
            conn.close()
            return f"⏰ Tarefa criada para **{run_at.strftime('%d/%m %H:%M')}**: {task_desc[:80]}"

        # show_xtb_account handled below

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

        elif command == 'reload_ia':
            try:
                from modules.ai_router import reload_and_validate, _last_validation
                _last_validation.clear()
                results = reload_and_validate()
                parts = ["🔄 **Recarregamento concluído:**"]
                for prov, r in results.items():
                    icon = "✅" if r['ok'] else "❌"
                    parts.append(icon + " **" + prov + "**: " + str(r['status']) + " (" + str(r['ms']) + "ms)")
                ok_n = sum(1 for r in results.values() if r['ok'])
                parts.append("**" + str(ok_n) + "/" + str(len(results)) + " APIs funcionais**")
                if ok_n == 0:
                    parts.append("⚠️ Verifica as API Keys no Render → Environment")
                return "\n".join(parts)
            except Exception as e:
                return "❌ Erro no reload: " + str(e)[:150]

        elif command == 'status_ia':
            import os
            try:
                from modules.ai_router import get_validation_status
            except ImportError as e:
                return "❌ Erro ao importar ai_router: " + str(e)
            status   = get_validation_status()
            xtb_mode = os.environ.get('XTB_MODE', 'demo')

            parts = ["📊 **Status IA:**", ""]
            for name, info in status.items():
                key_ok  = info['key_set']
                last_ok = info.get('last_ok')
                icon    = "✅" if last_ok is True else ("❌" if last_ok is False else "⚪")
                key_lbl = "SET" if key_ok else "NOT SET"
                parts.append(icon + " **" + name + "**: chave=" + key_lbl +
                              " | " + str(info['last_status']) + " | " + str(info['last_ms']) + "ms")
            any_ok = any(i.get('last_ok') is True for i in status.values())
            parts.append("")
            parts.append("**XTB Modo:** " + xtb_mode.upper())
            parts.append("**Fallback:** " + ("SIM ⚠️" if not any_ok else "NÃO ✅"))
            parts.append("")
            parts.append("💡 Para re-testar: escreve `recarregar ia`")
            return "\n".join(parts)

        elif command == 'connect_xtb':
            # Tenta login XTB e mostra estado + saldo
            import os
            mode = os.environ.get('XTB_MODE', 'demo')
            has_account = bool(os.environ.get('XTB_ACCOUNT_ID'))
            has_password = bool(os.environ.get('XTB_PASSWORD'))
            if not has_account or not has_password:
                return (
                    f"❌ XTB não configurado.\n\n"
                    f"Adiciona no Render → Environment:\n"
                    f"• `XTB_ACCOUNT_ID` = o teu ID XTB\n"
                    f"• `XTB_PASSWORD` = a tua password XTB\n"
                    f"• `XTB_MODE` = demo (ou real)\n\n"
                    f"Após configurar, faz redeploy e tenta novamente."
                )
            try:
                from modules.xtb import xtb_login, get_account_info
                session_data, err = xtb_login(mode=mode)
                if err:
                    return f"❌ Erro ao ligar ao XTB [{mode.upper()}]:\n{err}"
                account, err2 = get_account_info(session_data['token'])
                if err2 or not account:
                    return (
                        f"✅ Sessão XTB iniciada [{mode.upper()}]\n"
                        f"⚠️ Não foi possível obter saldo: {err2}\n\n"
                        f"Vai ao painel 📈 XTB para mais detalhes."
                    )
                return (
                    f"✅ **Sessão XTB iniciada [{mode.upper()}]**\n\n"
                    f"• Saldo: **{account.get('balance', 0)} {account.get('currency', 'EUR')}**\n"
                    f"• Equity: {account.get('equity', 0)}\n"
                    f"• Margem livre: {account.get('free_margin', 0)}\n\n"
                    f"Usa o painel 📈 XTB para gerir posições e ordens."
                )
            except Exception as e:
                return f"❌ Erro inesperado ao ligar XTB: {str(e)[:150]}"

        elif command == 'disconnect_xtb':
            return "✅ Sessão XTB terminada (as posições abertas continuam ativas no broker)."

        elif command == 'set_mode_demo':
            import os
            os.environ['XTB_MODE'] = 'demo'
            try:
                from modules.mod10 import save_state
                save_state(db_path, 'xtb_mode_override', 'demo')
            except Exception:
                pass
            return (
                "🟡 **XTB alterado para modo DEMO**\n\n"
                "• Ordens não são reais\n"
                "• Frase de autorização: `AUTORIZO EXECUÇÃO DEMO`\n"
                "• Para voltar ao real: escreve 'muda para modo real'"
            )

        elif command == 'set_mode_real':
            import os
            os.environ['XTB_MODE'] = 'real'
            try:
                from modules.mod10 import save_state
                save_state(db_path, 'xtb_mode_override', 'real')
            except Exception:
                pass
            return (
                "🔴 **XTB alterado para modo REAL**\n\n"
                "⚠️ As próximas ordens serão REAIS.\n"
                "• Frase de autorização: `AUTORIZO EXECUÇÃO REAL`\n"
                "• Requer também WebAuthn + PIN\n"
                "• Para voltar ao demo: escreve 'muda para modo demo'"
            )

        elif command == 'show_xtb_account':
            import os
            mode = os.environ.get('XTB_MODE', 'demo')
            if not os.environ.get('XTB_ACCOUNT_ID'):
                return "❌ XTB não configurado. Adiciona XTB_ACCOUNT_ID e XTB_PASSWORD no Render."
            try:
                from modules.xtb import xtb_login, get_account_info, get_positions
                session_data, err = xtb_login(mode=mode)
                if err:
                    return f"❌ Login XTB falhou: {err}"
                account, _ = get_account_info(session_data['token'])
                positions, _ = get_positions(session_data['token'])
                pos_text = ""
                if positions:
                    pos_text = f"\n\n**Posições abertas ({len(positions)}):**\n"
                    for p in positions[:5]:
                        profit = p.get('profit', 0)
                        pos_text += f"• {p.get('symbol')} {p.get('cmd')} — P&L: {'+'if profit>=0 else ''}{profit}€\n"
                return (
                    f"💼 **Conta XTB [{mode.upper()}]:**\n\n"
                    f"• Saldo: **{account.get('balance', 0)} {account.get('currency', 'EUR')}**\n"
                    f"• Equity: {account.get('equity', 0)}\n"
                    f"• Margem livre: {account.get('free_margin', 0)}"
                    f"{pos_text}"
                )
            except Exception as e:
                return f"❌ Erro: {str(e)[:150]}"

        elif command == 'show_portfolio':
            from modules.financial import get_portfolio_summary
            try:
                summary = get_portfolio_summary(user_id, db_path)
                ops = summary.get('operations', [])
                total = summary.get('total_invested', 0)
                profit = summary.get('total_profit', 0)
                if not ops:
                    return "📊 **Portfolio vazio.** Regista operações em 💹 Finanças → Registar Operação."
                lines = [f"📊 **Portfolio ({len(ops)} operações):**\n",
                         f"• Investido: {total:.2f}€",
                         f"• Resultado: {'+'if profit>=0 else ''}{profit:.2f}€\n"]
                for op in ops[:8]:
                    lines.append(f"• {op.get('asset','?')} {op.get('op_type','?')} — {op.get('result',0):.2f}€")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Erro ao carregar portfolio: {str(e)[:100]}"

        elif command == 'show_alerts':
            from modules.market_monitor import get_recent_alerts
            try:
                alerts = get_recent_alerts(user_id, db_path)
                if not alerts:
                    return "📡 **Sem alertas recentes.** O monitor está ativo e a vigiar os ativos."
                lines = [f"🔔 **Alertas recentes ({len(alerts)}):**\n"]
                for a in alerts[:10]:
                    lines.append(f"• {a.get('symbol','?')}: {a.get('message','')[:80]}")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Erro: {str(e)[:100]}"

        elif command == 'show_tasks':
            import sqlite3
            try:
                conn = sqlite3.connect(db_path, timeout=30)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,)
                ).fetchall()
                conn.close()
                if not rows:
                    return "📋 **Sem tarefas.** Cria tarefas no painel 📋 Tarefas."
                lines = [f"📋 **Tarefas ({len(rows)}):**\n"]
                for r in rows:
                    status_icon = {'done':'✅','pending':'⏳','scheduled':'⏰','error':'❌'}.get(r['status'],'•')
                    lines.append(f"{status_icon} {r['title'][:60]}")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Erro: {str(e)[:100]}"

        elif command == 'show_logs':
            import os
            try:
                data_dir = '/data' if os.path.exists('/data') else 'data'
                log_file = f'{data_dir}/logs/nexus.log'
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-20:]
                return "📄 **Últimas 20 linhas de log:**\n```\n" + "".join(lines)[-1200:] + "\n```"
            except Exception:
                return "📄 Sem logs disponíveis neste momento."

        elif command == 'enable_monitor':
            return (
                "📡 **Monitor 24/7 ativo** (já estava a correr).\n\n"
                "Para adicionar ativos: 'adiciona ativo SPY ao monitor'\n"
                "Para ver alertas: 'mostra alertas'\n"
                "Para verificar agora: vai ao painel 📡 Monitor → 🔍 Verificar Agora"
            )

        elif command == 'disable_monitor':
            return "⚠️ O monitor não pode ser desativado via chat (está integrado no servidor). Reinicia o servidor para parar."

        elif command == 'emergency_stop':
            from modules.security import emergency_stop as sec_stop
            sec_stop(user_id, db_path)
            return "🛑 **TRAVÃO DE EMERGÊNCIA ATIVADO**\nTodas as ações reais foram paradas."

        elif command == 'emergency_resume':
            from modules.security import emergency_resume as sec_resume
            sec_resume(user_id, db_path)
            return "▶ **Sistema retomado** — operações normais restabelecidas."

        else:
            # Unknown command - give helpful response
            logger.warning(f"Command '{command}' has no handler")
            return (
                f"⚠️ Comando **'{command}'** reconhecido mas sem implementação.\n\n"
                f"Comandos disponíveis:\n"
                f"• `mostra limites atuais`\n"
                f"• `mostra estado da nexus`\n"
                f"• `iniciar sessão xtb demo`\n"
                f"• `ver saldo`\n"
                f"• `define limite diário para 20€`\n"
                f"• `ativa modo seguro`\n"
                f"• `para tudo` (emergência)"
            )

    except Exception as e:
        logger.error(f"Execute command error [{command}]: {e}")
        return f"❌ Erro ao executar '{command}': {str(e)[:200]}"
