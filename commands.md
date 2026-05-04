# NEXUS — Lista Completa de Comandos

## Comandos Gerais

| Comando | Descrição |
|---|---|
| `nexus start` | Inicia o sistema NEXUS |
| `nexus stop` | Para o sistema NEXUS |
| `nexus restart` | Reinicia o sistema NEXUS |
| `nexus status` | Mostra o estado atual do sistema |
| `nexus version` | Mostra a versão instalada |
| `nexus help` | Mostra a ajuda geral de comandos |
| `nexus config` | Abre as configurações do sistema |
| `nexus logs` | Mostra os logs em tempo real |
| `nexus logs --tail N` | Mostra as últimas N linhas dos logs |
| `nexus logs --module <nome>` | Filtra logs por módulo |

---

## Core — Núcleo do Sistema

| Comando | Descrição |
|---|---|
| `nexus core status` | Estado do núcleo central |
| `nexus core init` | Inicializa o núcleo NEXUS |
| `nexus core reset` | Reinicia o estado interno do núcleo |
| `nexus core diagnostics` | Executa diagnósticos internos |
| `nexus core memory` | Mostra uso de memória e contexto ativo |
| `nexus core context list` | Lista os contextos ativos |
| `nexus core context clear` | Limpa o contexto atual |
| `nexus core context save <nome>` | Guarda o contexto com um nome |
| `nexus core context load <nome>` | Carrega um contexto guardado |

---

## Web Intelligence — Pesquisa e Inteligência Web

| Comando | Descrição |
|---|---|
| `nexus web search "<query>"` | Pesquisa na web sobre um tópico |
| `nexus web search --deep "<query>"` | Pesquisa aprofundada com múltiplas fontes |
| `nexus web scrape <url>` | Extrai conteúdo de uma página web |
| `nexus web scrape --full <url>` | Extrai todo o conteúdo incluindo links |
| `nexus web monitor <url>` | Monitoriza alterações numa página |
| `nexus web monitor --interval <s> <url>` | Define intervalo de monitorização (segundos) |
| `nexus web monitor stop <url>` | Para a monitorização de uma página |
| `nexus web trend "<tema>"` | Analisa tendências sobre um tema |
| `nexus web news "<tema>"` | Recolhe notícias recentes sobre um tema |
| `nexus web competitor <url>` | Analisa um site concorrente |
| `nexus web summarize <url>` | Resume o conteúdo de uma página |

---

## Profit Engine — Motor de Rentabilidade

| Comando | Descrição |
|---|---|
| `nexus profit analyze` | Analisa oportunidades de receita ativas |
| `nexus profit report` | Gera relatório de rentabilidade |
| `nexus profit report --period <dia/semana/mês>` | Relatório por período |
| `nexus profit opportunities` | Lista oportunidades identificadas |
| `nexus profit opportunities --filter <categoria>` | Filtra por categoria |
| `nexus profit forecast` | Previsão de receita para os próximos períodos |
| `nexus profit optimize` | Sugere otimizações para maximizar lucro |
| `nexus profit track <id>` | Rastreia uma oportunidade específica |
| `nexus profit score <id>` | Pontuação de uma oportunidade |
| `nexus profit pipeline` | Mostra o pipeline de oportunidades ativo |
| `nexus profit add "<descrição>"` | Adiciona uma nova oportunidade manualmente |

---

## Auto Evolution — Auto-Evolução e Aprendizagem

| Comando | Descrição |
|---|---|
| `nexus evolve status` | Estado do módulo de auto-evolução |
| `nexus evolve run` | Executa um ciclo de auto-evolução |
| `nexus evolve schedule` | Agenda ciclos automáticos de evolução |
| `nexus evolve history` | Histórico de evoluções realizadas |
| `nexus evolve diff` | Mostra alterações da última evolução |
| `nexus evolve rollback` | Reverte a última evolução |
| `nexus evolve rollback --to <versão>` | Reverte para uma versão específica |
| `nexus evolve benchmark` | Avalia performance antes/após evolução |
| `nexus evolve suggest` | Sugere melhorias sem aplicar |
| `nexus evolve apply "<sugestão>"` | Aplica uma sugestão específica |
| `nexus evolve lock` | Bloqueia evoluções automáticas |
| `nexus evolve unlock` | Desbloqueia evoluções automáticas |

---

## Multi-IA — Orquestração de Múltiplas IAs

| Comando | Descrição |
|---|---|
| `nexus ia list` | Lista todas as IAs configuradas |
| `nexus ia status` | Estado de cada IA no sistema |
| `nexus ia add <nome> --model <modelo>` | Adiciona uma nova IA ao sistema |
| `nexus ia remove <nome>` | Remove uma IA do sistema |
| `nexus ia assign <tarefa> --to <nome>` | Atribui uma tarefa a uma IA específica |
| `nexus ia ask <nome> "<pergunta>"` | Envia uma pergunta a uma IA específica |
| `nexus ia broadcast "<mensagem>"` | Envia uma mensagem a todas as IAs |
| `nexus ia collaborate "<tarefa>"` | Inicia colaboração multi-IA numa tarefa |
| `nexus ia vote "<questão>"` | Pede votação/consenso entre as IAs |
| `nexus ia orchestrate "<objetivo>"` | Orquestra as IAs para atingir um objetivo |
| `nexus ia sync` | Sincroniza contexto entre todas as IAs |
| `nexus ia performance` | Relatório de performance por IA |

---

## Reports — Relatórios e Análises

| Comando | Descrição |
|---|---|
| `nexus report daily` | Gera o relatório diário completo |
| `nexus report weekly` | Gera o relatório semanal |
| `nexus report monthly` | Gera o relatório mensal |
| `nexus report custom --from <data> --to <data>` | Relatório por intervalo de datas |
| `nexus report export --format <pdf/csv/json>` | Exporta relatório num formato |
| `nexus report schedule --cron "<expressão>"` | Agenda relatórios automáticos |
| `nexus report list` | Lista relatórios gerados |
| `nexus report open <id>` | Abre um relatório específico |
| `nexus report delete <id>` | Apaga um relatório |
| `nexus report insights` | Extrai insights automáticos dos dados |

---

## Data — Gestão de Dados

| Comando | Descrição |
|---|---|
| `nexus data list` | Lista os datasets disponíveis |
| `nexus data import <ficheiro>` | Importa um ficheiro de dados |
| `nexus data export <nome> --format <formato>` | Exporta um dataset |
| `nexus data clean <nome>` | Limpa e normaliza um dataset |
| `nexus data analyze <nome>` | Análise estatística de um dataset |
| `nexus data merge <nome1> <nome2>` | Combina dois datasets |
| `nexus data delete <nome>` | Apaga um dataset |
| `nexus data backup` | Faz backup de todos os dados |
| `nexus data restore <backup>` | Restaura a partir de um backup |
| `nexus data stats` | Estatísticas globais do armazenamento |

---

## Logs — Gestão de Logs

| Comando | Descrição |
|---|---|
| `nexus logs show` | Mostra logs recentes |
| `nexus logs show --level <debug/info/warn/error>` | Filtra por nível |
| `nexus logs show --module <nome>` | Filtra por módulo |
| `nexus logs search "<termo>"` | Pesquisa nos logs |
| `nexus logs clear` | Limpa todos os logs |
| `nexus logs archive` | Arquiva logs antigos |
| `nexus logs export --format <txt/json>` | Exporta logs |
| `nexus logs tail` | Segue logs em tempo real |
| `nexus logs stats` | Estatísticas de erros e avisos |

---

## Automações e Fluxos

| Comando | Descrição |
|---|---|
| `nexus flow list` | Lista os fluxos automáticos configurados |
| `nexus flow create "<nome>"` | Cria um novo fluxo |
| `nexus flow run <nome>` | Executa um fluxo manualmente |
| `nexus flow enable <nome>` | Ativa um fluxo automático |
| `nexus flow disable <nome>` | Desativa um fluxo automático |
| `nexus flow edit <nome>` | Edita um fluxo existente |
| `nexus flow delete <nome>` | Apaga um fluxo |
| `nexus flow history <nome>` | Histórico de execuções de um fluxo |
| `nexus flow schedule <nome> --cron "<expressão>"` | Agenda um fluxo |

---

## Notificações e Alertas

| Comando | Descrição |
|---|---|
| `nexus alert list` | Lista alertas configurados |
| `nexus alert add --event <evento> --channel <canal>` | Adiciona um alerta |
| `nexus alert remove <id>` | Remove um alerta |
| `nexus alert test <id>` | Testa um alerta |
| `nexus notify send "<mensagem>" --channel <canal>` | Envia notificação manual |
| `nexus notify history` | Histórico de notificações enviadas |

---

## Sistema e Manutenção

| Comando | Descrição |
|---|---|
| `nexus system info` | Informações do sistema e hardware |
| `nexus system health` | Verificação de saúde geral |
| `nexus system update` | Atualiza o NEXUS para a versão mais recente |
| `nexus system upgrade --module <nome>` | Atualiza um módulo específico |
| `nexus system clean` | Limpa ficheiros temporários e cache |
| `nexus system reset --confirm` | Reinicia o sistema ao estado inicial |
| `nexus system backup` | Backup completo do sistema |
| `nexus system restore <backup>` | Restaura backup completo |
| `nexus system env` | Mostra variáveis de ambiente ativas |
| `nexus system env set <KEY>=<VALUE>` | Define uma variável de ambiente |

---

## Live Mode — Modo de Produção

### Iniciar / Parar

| Comando | Descrição |
|---|---|
| `python nexus_live.py` | Inicia o NEXUS em modo LIVE (foreground) |
| `python nexus_live.py --config config/live_runtime.json` | Inicia com configuração personalizada |
| `python nexus_live.py --dry-run` | Inicia em modo seguro (todos os pipelines em dry_run) |
| `python nexus_live.py --no-scheduler` | Inicia sem agendamento automático (runs manuais apenas) |

### CLI Controller (`nexus_cli.py`)

| Comando | Descrição |
|---|---|
| `python nexus_cli.py start` | Inicia o runtime LIVE em foreground |
| `python nexus_cli.py start --detach` | Inicia em background (escreve PID file) |
| `python nexus_cli.py start --config config/live_runtime.json` | Inicia com config específica |
| `python nexus_cli.py start --dry-run` | Inicia com todos os pipelines em modo dry_run |
| `python nexus_cli.py stop` | Envia SIGTERM ao processo em background (leitura do PID file) |
| `python nexus_cli.py status` | Mostra estado completo do runtime (módulos, pipelines, audit log) |
| `python nexus_cli.py status --json` | Estado em formato JSON estruturado |
| `python nexus_cli.py run intelligence` | Executa o pipeline de inteligência imediatamente |
| `python nexus_cli.py run financial` | Executa o pipeline financeiro imediatamente |
| `python nexus_cli.py run evolution` | Executa o pipeline de auto-evolução imediatamente |
| `python nexus_cli.py run consensus` | Executa o pipeline de consenso multi-IA imediatamente |
| `python nexus_cli.py run reporting` | Executa o pipeline de relatórios imediatamente |
| `python nexus_cli.py run <pipeline> --export <path>` | Executa e exporta resultado para JSON |
| `python nexus_cli.py report` | Corre todos os pipelines e gera relatório consolidado |
| `python nexus_cli.py report --pipeline <nome>` | Relatório de um pipeline específico |
| `python nexus_cli.py report --export reports/live/report.json` | Exporta relatório para path específico |

### Ficheiros de Configuração

| Ficheiro | Descrição |
|---|---|
| `config/live_runtime.json` | Configuração principal do runtime LIVE (todos os módulos) |
| `config/live_pipelines.json` | Agendamento, dependências e triggers por pipeline |

### Pastas de Saída (LIVE)

| Pasta | Descrição |
|---|---|
| `logs/live/` | Logs e audit chain do modo LIVE (`audit_live.jsonl`, `nexus.pid`) |
| `reports/live/` | Relatórios exportados automaticamente pelo pipeline de reporting |

---

---

## Command Layer — Chat Grammar (Natural Language)

The `CommandEngine` in `nexus_commands/` accepts free-form natural-language
input and maps it to runtime actions without requiring exact syntax.

### Verb vocabulary

| Canonical verb | Accepted synonyms |
|---|---|
| `run` | execute, trigger, launch, fire |
| `show` | display, get, view, fetch, what, what's |
| `generate` | create, build, export, produce, make |
| `start` | activate, boot, turn on |
| `stop` | halt, kill, shutdown, deactivate |
| `enable` | switch on, activate |
| `disable` | switch off, turn off, deactivate |
| `increase` | raise, up, boost, bump, higher |
| `decrease` | lower, reduce, drop, cut |
| `set` | change, update, assign, configure, modify |
| `pause` | freeze, hold, suspend |
| `resume` | unpause, continue, restore |
| `reset` | clear, reinit, restart |
| `list` | ls, all |
| `check` | verify, validate, inspect, examine |

### Target vocabulary

| Canonical target | Accepted synonyms / shorthands |
|---|---|
| `pipeline` | pipelines, pipe — or use the pipeline name directly |
| `report` | reports |
| `risk` | drawdown, exposure |
| `module` | modules, component, subsystem — or use the module name directly |
| `audit` | audit chain, chain, log, logs |
| `state` | checkpoint, counters |
| `evolution` | auto evolution, auto-evolution |
| `intelligence` | intel, market intelligence |
| `consensus` | vote, agreement |
| `financial` | finance, portfolio |
| `limit` | limits, threshold, parameter — or use limit name directly |
| `status` | health, overview, info |
| `history` | runs, executions, recent |
| `scheduler` | schedule, scheduling |

### Command grammar examples

#### Run

| Natural-language input | Action |
|---|---|
| `run pipeline intelligence` | Run the intelligence pipeline |
| `run intelligence` | Same — shorthand |
| `run all pipelines` | Run all 5 pipelines |
| `execute financial` | Run the financial pipeline |
| `trigger consensus` | Run the consensus pipeline |

#### Show / List

| Natural-language input | Action |
|---|---|
| `show status` | Full runtime status |
| `what is the status` | Same |
| `list pipeline` | All pipelines with mode and interval |
| `show module profit_engine` | Health of a specific module |
| `show risk` | Current risk / alert thresholds |
| `show audit 20` | Last 20 audit entries |
| `show history` | Last 10 pipeline run records |
| `show state` | Cycle count, uptime, last cycle |

#### Generate

| Natural-language input | Action |
|---|---|
| `generate report` | Run all pipelines and export report |
| `generate report financial` | Report scoped to financial pipeline |
| `generate report financial export reports/live/fin.json` | Same + export to path |
| `generate checkpoint` | Force a state checkpoint now |
| `verify audit chain` | Check audit chain integrity |

#### Enable / Disable

| Natural-language input | Action |
|---|---|
| `enable module auto_evolution` | Start a stopped module |
| `disable module web_intelligence` | Stop a module ⚠ confirm |
| `start pipeline reporting` | Set pipeline mode to enabled |
| `stop pipeline evolution` | Disable a pipeline ⚠ confirm |
| `enable evolution` | Allow evolution to apply patches ⚠ confirm |
| `disable evolution` | Set evolution back to dry-run |

#### Start / Stop Scheduler

| Natural-language input | Action |
|---|---|
| `start scheduler` | Enable automatic pipeline scheduling |
| `stop scheduler` | Pause the scheduler ⚠ confirm |
| `pause pipeline` | Pause runtime scheduler |
| `resume pipeline` | Resume paused scheduler |

#### Set / Increase / Decrease Limits

| Natural-language input | Action |
|---|---|
| `set limit max_drawdown 0.15` | Set drawdown alert to 15% ⚠ confirm |
| `set max_drawdown to 0.12` | Same — shorthand |
| `increase limit sentiment_threshold 0.1` | Raise threshold by 0.1 |
| `increase sentiment threshold by 10%` | Raise threshold by 10% |
| `decrease limit sharpe_alert 0.1` | Lower Sharpe alert ⚠ confirm |
| `increase drawdown 5%` | Raise drawdown limit by 5% |

#### Mutable limits

| Limit name | Aliases | Config section |
|---|---|---|
| `max_drawdown_alert` | `max_drawdown`, `drawdown` | `financial` |
| `sharpe_alert` | `sharpe`, `sharpe_ratio` | `financial` |
| `sentiment_threshold` | `sentiment` | `intelligence` |
| `max_urls` | `urls` | `intelligence` |
| `max_patches_per_cycle` | `patches`, `max_patches` | `evolution` |
| `n_agents` | `agents` | `consensus` |
| `agreement_alert` | `agreement` | `consensus` |

### Safe mode

`CommandEngine` starts with `safe_mode=True`. Destructive operations (stop,
disable, decrease, set, reset) are **blocked** and return a response with
`requires_confirm=True`. Call `.confirm()` to proceed:

```python
engine = CommandEngine(runtime, safe_mode=True)
resp = engine.execute("stop scheduler")
# resp.requires_confirm == True
resp = resp.confirm()           # executes the command
```

Disable safe mode for unattended scripts:

```python
engine.safe_mode = False
```
## Dashboard — Interface Web (Fase 8)

### Iniciar

| Comando | Descrição |
|---|---|
| `python nexus_cli.py dashboard` | Abre o dashboard em http://127.0.0.1:7000 |
| `python nexus_cli.py dashboard --port 8080` | Dashboard numa porta personalizada |
| `python nexus_cli.py dashboard --host 0.0.0.0 --port 7000` | Abre para todas as interfaces |

### Rotas disponíveis

| Rota | Descrição |
|---|---|
| `http://localhost:7000/` | Visão geral — modo, módulos, pipelines, uptime |
| `http://localhost:7000/pipelines` | Configuração e estado de cada pipeline |
| `http://localhost:7000/signals` | Últimos sinais do Signal Engine |
| `http://localhost:7000/risk` | Métricas de risco e drawdown |
| `http://localhost:7000/audit` | Últimas 50 entradas do log de auditoria |
| `http://localhost:7000/reports` | Lista de relatórios exportados (reports/live/) |
| `http://localhost:7000/reports/<nome>` | Visualização de um relatório JSON |
| `http://localhost:7000/limits` | Limites e configurações do runtime |

### Características

- Servidor Python puro (`http.server`) — sem dependências externas
- Apenas leitura — não modifica o estado do runtime
- Auto-refresh a cada 30 segundos
- Lê ficheiros em tempo real: `logs/live/*.json`, `data/runtime/*.json`, `reports/live/*.json`

### Python API

```python
from nexus_commands import CommandEngine
from nexus_runtime import NexusRuntime

runtime = NexusRuntime.live()
runtime.start()
engine  = CommandEngine(runtime)

resp = engine.execute("run pipeline intelligence")
print(resp)                      # structured CommandResponse

resp = engine.execute("show history 20")
entries = resp.data["history"]

print(engine.help("show"))       # help for all 'show' commands
print(engine.help("set limit"))  # help for a specific command
```

---

## Signal Engine — Chat Commands

The Signal Engine (`nexus_runtime/signal_engine.py`) fuses pattern detection,
sentiment analysis, and multi-IA consensus into actionable trade signals.
All five commands are available through the natural-language `CommandEngine`.

### Commands

| Natural-language input | Action |
|---|---|
| `signal <symbol>` | Full signal pipeline: patterns + sentiment + IA consensus |
| `analyze <symbol>` | Alias for `signal` |
| `scan <symbol>` | Alias for `signal` (synonym) |
| `evaluate <symbol>` | Alias for `signal` (synonym) |
| `entry <symbol>` | Entry readiness only (no IA consensus — faster) |
| `buy <symbol>` | Alias for `entry` |
| `exit <symbol>` | Exit readiness for an open position |
| `sell <symbol>` | Alias for `exit` |
| `analyze risk <symbol>` | Risk metrics only: volatility, drawdown, position size |
| `show signal` | Last 10 signals in engine history |
| `show signal 20` | Last N signals in engine history |

### Examples

```
signal BTC
→ BTC: BUY  strength=0.72  risk=0.12  → ENTER

entry ETH
→ ETH: ✓ ENTER  side=BUY  confidence=0.68

exit BTC
→ BTC: ✗ HOLD  urgency=low  pnl_estimate=0.0215

analyze risk AAPL
→ AAPL: risk_score=0.08  vol=1.20%  drawdown=0.00%  pos_size=5.00%

show signal 5
→ Last 5 signals in engine history.
```

### Signal output fields

| Field | Description |
|---|---|
| `side` | `buy` / `sell` / `hold` — directional recommendation |
| `strength` | 0–1 — signal conviction (0 = no view, 1 = maximum) |
| `entry.should_enter` | Boolean — whether entry conditions are met |
| `entry.confidence` | 0–1 composite score (pattern × 0.4 + sentiment × 0.2 + consensus × 0.4) |
| `entry.pattern_score` | 0–1 from PatternDetector (0.5 = neutral) |
| `entry.sentiment_score` | 0–1 from NewsAnalyzer (0.5 = neutral) |
| `entry.consensus_score` | 0–1 from multi-IA vote (0.5 = neutral) |
| `exit.should_exit` | Boolean — whether exit is recommended |
| `exit.urgency` | `low` / `medium` / `high` / `immediate` |
| `risk.volatility` | ATR/price normalised volatility |
| `risk.drawdown_pct` | Current drawdown from equity peak |
| `risk.position_size` | Suggested position size (fraction of capital, quarter-Kelly, max 5%) |
| `risk.stop_loss_pct` | Suggested stop-loss distance |
| `risk.take_profit_pct` | Suggested take-profit distance (2× stop-loss) |
| `risk.risk_score` | 0–1 composite risk score |

### Pipeline integration

The Signal Engine runs automatically inside four pipelines:

| Pipeline | Signal Engine role |
|---|---|
| `intelligence` | Generates full signals for symbols with detected patterns (max 5 per cycle) |
| `financial` | Computes risk metrics for all open positions |
| `consensus` | Runs IA consensus vote per symbol found in intelligence patterns |
| `reporting` | Exports last 10 signals to `reports/live/signals_latest.json` |

### Python API

```python
from nexus_runtime import NexusRuntime
from nexus_runtime.signal_engine import SignalEngine

runtime = NexusRuntime.live()
runtime.start()

se = SignalEngine.from_runtime(runtime)

result = se.generate_signal("BTC")
print(result.side, result.strength)
print(result.entry.should_enter, result.entry.reasons)
print(result.risk.to_dict())

entry = se.evaluate_entry("ETH")
exit_ = se.evaluate_exit("BTC")
risk  = se.compute_risk("AAPL")
from dashboard import DashboardServer, start_dashboard

# Foreground (bloqueante)
start_dashboard(host="127.0.0.1", port=7000)

# Background (thread)
srv = DashboardServer(host="127.0.0.1", port=7000)
srv.start_background()
print(f"Dashboard em {srv.url}")
# ...
srv.stop()
```

---

## Evolution Engine — Evolução Controlada de Parâmetros (Fase 9)

### Comandos de chat (Command Layer)

| Comando | Descrição |
|---|---|
| `evolve` | Avalia performance, aprende com sinais e propõe ajustes |
| `NEXUS, evolui.` | Variante em português (sinónimo de `evolve`) |
| `show evolution` | Mostra propostas pendentes e estado atual |
| `propose evolution` | Alias para `show evolution` |
| `NEXUS, mostra propostas de evolução.` | Variante em português |
| `apply evolution` | Aplica todas as propostas pendentes (requer confirmação) |
| `NEXUS, aplica evolução.` | Variante em português |
| `rollback evolution` | Reverte o último passo de evolução (requer confirmação) |
| `rollback evolution 2` | Reverte os últimos 2 passos |
| `NEXUS, reverte a última evolução.` | Variante em português |
| `show evolution history` | Histórico de evoluções aplicadas |
| `show evolution history 5` | Últimos 5 registos do histórico |

### Fluxo de trabalho típico

```
1. evolve                     → avalia + propõe
2. show evolution             → revê propostas
3. apply evolution            → aplica (pede confirmação)
   .confirm()                 → confirma a aplicação
4. rollback evolution         → reverte se necessário
   .confirm()                 → confirma o rollback
```

### Perfil BALANCED — restrições de segurança

| Restrição | Valor |
|---|---|
| Variação máxima por parâmetro por ciclo | 15% do valor atual |
| Máximo de propostas por ciclo | 4 |
| Mínimo de sinais para propor mudanças | 3 |
| Cap: `intelligence.sentiment_threshold` | [0.05, 0.90] |
| Cap: `financial.max_drawdown_alert` | [0.03, 0.25] |
| Cap: `financial.sharpe_alert` | [0.05, 3.00] |
| Cap: `consensus.agreement_alert` | [0.15, 0.85] |

### Parâmetros ajustáveis

| Parâmetro | Descrição |
|---|---|
| `intelligence.sentiment_threshold` | Limiar de alerta de sentimento |
| `financial.max_drawdown_alert` | Limiar de alerta de drawdown |
| `financial.sharpe_alert` | Limiar de alerta do rácio de Sharpe |
| `consensus.agreement_alert` | Limiar de alerta de divergência de consenso |

### Auditoria e rastreabilidade

- Cada apply/rollback escreve em `logs/evolution_live.jsonl`
- Cada entrada inclui: `evo_id`, `action`, `ts`, `proposals`, `snapshot_before`, `snapshot_after`, `hash`, `prev_hash`
- Rollback restaura o `snapshot_before` do step mais antigo revertido
- Audit chain auditada em `logs/live/audit_live.jsonl`

### Dashboard

- Rota `/evolution` no dashboard mostra:
  - Métricas de performance usadas para evolução
  - Propostas pendentes
  - Ajustes ativos (último apply)
  - Histórico de evolução (logs/evolution_live.jsonl)

### Python API

```python
from nexus_runtime import NexusRuntime
from nexus_runtime.evolution_engine import EvolutionEngine

runtime = NexusRuntime.live()
runtime.start()

ee = EvolutionEngine.from_runtime(runtime)

# Avaliar performance
perf = ee.evaluate_performance()
print(perf.hit_rate, perf.volatility_regime)

# Aprender com sinais
learn = ee.learn_from_signals()
print(learn.patterns_worked, learn.risk_too_tight)

# Propor ajustes
proposals = ee.propose_adjustments(perf, learn)
for p in proposals:
    print(p.parameter, p.current_value, "→", p.proposed_value, f"({p.change_pct:+.1f}%)")

# Aplicar
result = ee.apply_adjustments(proposals)
print(result.applied_count, result.evo_id)

# Reverter
rb = ee.rollback(last_n=1)
print(rb.rolled_back, rb.evo_ids)

# Histórico
for entry in ee.history(limit=10):
    print(entry["ts"], entry["action"], len(entry["proposals"]))
```

---

## IBKR Integration — Integração com Interactive Brokers (Fase 11)

### Modos de operação

| Modo | Comportamento |
|---|---|
| `paper` | Simulação — ordens preenchidas instantaneamente sem IO real |
| `semi` | Ordens ficam pendentes até o utilizador confirmar com `ibkr confirm ORDER_ID` |
| `auto` | Execução automática imediata dentro de todos os limites de risco |

> **IBKR começa sempre em modo `paper`. Para activar `semi` ou `auto` requer confirmação explícita.**

### Comandos de chat (Command Layer)

| Comando | Descrição | Confirmar? |
|---|---|---|
| `ibkr status` | Estado completo: modo, saldo, posições, risk | — |
| `ibkr positions` | Lista posições abertas com PnL | — |
| `ibkr balance` | Saldo e breakdown de capital por bucket | — |
| `ibkr orders` | Ordens abertas e recentes | — |
| `ibkr mode auto` | Ativa modo automático | ⚠ sim |
| `ibkr mode semi` | Ativa modo semi (confirmação manual) | ⚠ sim |
| `ibkr mode paper` | Volta a modo paper (simulação) | ⚠ sim |
| `ibkr enable auto` | Alias para `ibkr mode auto` | ⚠ sim |
| `ibkr capital 1000` | Define limite máximo de capital deployável | ⚠ sim |
| `ibkr set capital 500` | Alias para `ibkr capital X` | ⚠ sim |
| `ibkr close BTC` | Fecha posição aberta em BTC | ⚠ sim |
| `ibkr safe mode` | Entra em safe mode — bloqueia todas as novas trades | — |
| `ibkr resume` | Sai do safe mode e retoma operações | ⚠ sim |
| `ibkr confirm ORD-001` | Confirma uma ordem pendente (modo semi) | — |

### Variantes em português natural

| Input | Equivalente |
|---|---|
| `NEXUS, ativa modo automático.` | `ibkr mode auto` |
| `NEXUS, ativa modo semi.` | `ibkr mode semi` |
| `NEXUS, ativa modo paper.` | `ibkr mode paper` |
| `NEXUS, usa no máximo 800 euros.` | `ibkr capital 800` |
| `NEXUS, fecha BTC.` | `ibkr close BTC` |
| `NEXUS, fecha ETH.` | `ibkr close ETH` |
| `NEXUS, entra em safe mode.` | `ibkr safe mode` |
| `NEXUS, retoma operações.` | `ibkr resume` |
| `confirmar ordem ORD-001` | `ibkr confirm ORD-001` |

### Limites de risco (fixos — não modificáveis pelo utilizador)

| Parâmetro | Valor | Descrição |
|---|---|---|
| `max_risk_per_trade` | 0.5% | Risco máximo por posição (% do capital) |
| `max_daily_risk` | 1.0% | Risco acumulado máximo por dia |
| `max_weekly_risk` | 2.0% | Risco acumulado máximo por semana |
| `max_drawdown` | 5.0% | Drawdown que activa safe mode automático |

### Gestão de capital — Fase de recuperação

Enquanto `recovered_capital < initial_capital`, todos os lucros vão para recuperação.
Nenhum reinvestimento ou uso dos fundos é permitido.

Após recuperação, o capital é dividido em 3 buckets:

| Bucket | % | Descrição |
|---|---|---|
| `tools_fund` | 30% | Custos operacionais e infraestrutura |
| `reinvest_fund` | 50% | Reinvestido em novas posições |
| `standby_fund` | 20% | Congelado — requer `authorise_standby(amount)` explícito |

### Regra do limite de capital (hard cap)

O NEXUS **nunca** pode deployer mais do que `user_capital_limit` sem comando explícito do utilizador.
Aumentar o limite requer `ibkr capital NOVO_LIMITE`.

### Audit chain

Cada acção IBKR escreve em dois ficheiros com encadeamento SHA-256:
- `logs/ibkr_orders.jsonl` — log de todas as ordens
- `logs/audit_chain.jsonl` — audit chain global

Cada entrada tem os campos `hash` (SHA-256) e `prev_hash` (hash da entrada anterior), formando uma cadeia à prova de adulteração.

### Dashboard — Rotas IBKR

| Rota | Descrição |
|---|---|
| `http://localhost:7000/ibkr` | Overview: modo, estado, saldo, risco |
| `http://localhost:7000/ibkr/positions` | Posições abertas com PnL |
| `http://localhost:7000/ibkr/orders` | Ordens pendentes e histórico recente |
| `http://localhost:7000/ibkr/capital` | Capital, buckets e accumuladores de risco |

> Todas as rotas são **só de leitura** — lêem de `data/ibkr/` e `logs/ibkr_orders.jsonl`.

### Configuração (`config/live_runtime.json`)

```json
"ibkr": {
  "mode": "paper",
  "enabled": false,
  "initial_capital": 0.0,
  "user_capital_limit": 0.0,
  "recovery_enabled": true,
  "tools_fund_pct": 0.30,
  "reinvest_fund_pct": 0.50,
  "standby_fund_pct": 0.20,
  "max_risk_per_trade": 0.005,
  "max_daily_risk": 0.010,
  "max_weekly_risk": 0.020,
  "max_drawdown": 0.050,
  "host": "127.0.0.1",
  "port": 7497,
  "client_id": 1
}
```

> `port: 7497` = TWS paper trading. Para live TWS usar `port: 7496`.

### Python API

```python
from nexus_runtime import NexusRuntime
from nexus_runtime.ibkr_integration import IBKRIntegration
from nexus_runtime.capital_manager import CapitalManager
from nexus_runtime.risk_manager import RiskManager

# Construir a partir do runtime
runtime = NexusRuntime.live()
ibkr = IBKRIntegration.from_runtime(runtime)
ibkr.connect()

# Estado
print(ibkr.status())

# Colocar uma ordem (paper mode)
result = ibkr.place_order(
    symbol="BTC",
    side="buy",
    size=0.01,
    price=50000.0,
    sl=49000.0,
    tp=52000.0,
)
print(result.order_id, result.status)   # e.g. "ORD-001", "simulated"

# Confirmar uma ordem pendente (semi mode)
result = ibkr.confirm_pending("ORD-001")

# Fechar posição
close_result = ibkr.close_position("BTC")
print(close_result.pnl)

# Safe mode
ibkr.enter_safe_mode("Drawdown atingiu 5%")
ibkr.exit_safe_mode()

# Capital manager
cap = ibkr._capital
cap.setup(initial_capital=1000.0, user_capital_limit=800.0)
print(cap.status())

# Risk manager
risk = ibkr._risk
ok, reason = risk.validate_trade(capital=1000.0, risk_amount=4.0)
print(ok, reason)
```

---

*Documentação gerada automaticamente pelo sistema NEXUS.*  
*Para ajuda detalhada sobre um comando: `nexus help <comando>`*
