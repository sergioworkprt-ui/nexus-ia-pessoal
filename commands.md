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
```

---

*Documentação gerada automaticamente pelo sistema NEXUS.*  
*Para ajuda detalhada sobre um comando: `nexus help <comando>`*
