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

*Documentação gerada automaticamente pelo sistema NEXUS.*  
*Para ajuda detalhada sobre um comando: `nexus help <comando>`*
