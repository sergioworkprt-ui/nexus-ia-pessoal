# NEXUS V2 — Arquitectura Técnica Completa

> Documento gerado a partir da leitura directa do código-fonte.  
> Branch: `claude/create-test-file-d1AY6` — Última actualização: 2026-05-13

---

## Índice

1. [Arquitectura Geral](#1-arquitectura-geral)
2. [Componentes em Detalhe](#2-componentes-em-detalhe)
3. [Arranque do Sistema](#3-arranque-do-sistema)
4. [Arquitectura do VPS](#4-arquitectura-do-vps)
5. [Arquitectura CI/CD](#5-arquitectura-cicd)
6. [Arquitectura de Segurança](#6-arquitectura-de-segurança)
7. [Escalabilidade](#7-escalabilidade)

---

## 1. Arquitectura Geral

### 1.1 Diagrama Lógico

```
┌────────────────────────────────────────────────────────────────────┐
│                         BROWSER / CLIENTE                          │
│                                                                    │
│   ┌────────────────┐      ┌────────────────┐      ┌──────────────┐   │
│   │ React + Vite  │      │  fetch() /api/*  │      │ WebSocket  │   │
│   │ (bundle em    │────►│  (REST calls)   │────►│ ws://:8801  │   │
│   │ /opt/nexus/   │      │                 │      │ (real-time)│   │
│   │ frontend/dist)│      └────────────────┘      └──────────────┘   │
│   └────────────────┘                                                  │
└────────────────────────────────────────────────────────────────────┘
         │ HTTP :9000              │ HTTP :9000              │
         ▼                        ▼                        ▼
┌──────────────────────┐     ┌───────────────────────┐  ┌─────────────────┐
│  nexus-dashboard       │     │  nexus-dashboard          │  │  nexus-ws        │
│  FastAPI :9000         │     │  proxy /api/* → :8000    │  │  websockets :8801│
│  serve React SPA       │     │  (httpx AsyncClient)      │  │  broadcast JSON  │
│  Cache-Control headers │     └───────────────────────┘  └─────────────────┘
└──────────────────────┘              │ HTTP :8000
                                            ▼
                          ┌───────────────────────────────┐
                          │        nexus-core              │
                          │  FastAPI REST API :8000         │
                          │  nexus.main → uvicorn           │
                          │  nexus.api.rest.main:app        │
                          │                                │
                          │  MODO COMPLETO                 │
                          │  ├─ Orchestrator               │
                          │  ├─ Memory                     │
                          │  ├─ Security / JWT             │
                          │  ├─ Tasks                      │
                          │  ├─ Learning (multi-LLM)       │
                          │  ├─ Trading (XTB + IBKR)       │
                          │  ├─ ML, Watchdog, Evolution    │
                          │  ├─ TruthChecker, VideoAnalysis│
                          │  └─ TTS / STT                  │
                          │                                │
                          │  WS thread (daemon)            │
                          │  asyncio.new_event_loop()      │
                          │  └─ ws_server.py :8801         │
                          └───────────────────────────────┘
                                       │ registo de módulos
                          ┌───────────────────────────────┐
                          │        nexus-api               │
                          │  FastAPI REST API :8001         │
                          │  nexus.api.rest.main:app        │
                          │  (instância autónoma)          │
                          │  /chat sem auth (fallback)     │
                          └───────────────────────────────┘
```

### 1.2 Portas e Protocolos

| Porta | Protocolo | Serviço | Função |
|-------|-----------|---------|--------|
| **9000** | HTTP | `nexus-dashboard` | Serve o SPA React e faz proxy `/api/*` → `:8000` |
| **8000** | HTTP | `nexus-core` | REST API completa do orquestrador |
| **8801** | WebSocket | `nexus-core` / `nexus-ws` | Push de eventos em tempo real para o dashboard |
| **8001** | HTTP | `nexus-api` | REST API autónoma (fallback / standalone) |

### 1.3 Fluxo de Dados — Request de Chat

```
Utilizador                Dashboard           nexus-dashboard      nexus-core
    │                        │                     │                  │
    │── escreve mensagem ──►│                     │                  │
    │                        │── POST /api/chat ──►│                  │
    │                        │                     │── POST /chat ──►│
    │                        │                     │   (httpx proxy)  │
    │                        │                     │                  │── Orchestrator.process()
    │                        │                     │                  │── Learning / LLM
    │                        │                     │                  │── Memory.store()
    │                        │                     │◄─ JSON response ─│
    │                        │◄─ 200 + {response} ─│                  │
    │◄── resposta mostrada ──│                     │                  │
    │                        │                     │                  │
    │  [WebSocket push]       │◄──────────────────────────────────►│
    │◄── estado WS actualizado │  {type:status, nexus_ready:true}     │
```

### 1.4 Fluxo de Dados — Actualizações em Tempo Real (WebSocket)

```
nexus-core (WS thread)              Dashboard (browser)
        │                                  │
        │── websockets.serve(:8801) ──────►│ wsUrl() = VITE_WS_URL
        │                                  │   (ws://35.241.151.115:8801)
        │◄──────────────────────────────│ connect()
        │── {type:"connected", mode} ─────►│ setWsStatus("online")
        │                                  │
        │── {type:"heartbeat"} ─────────►│ (a cada 30s, keepalive)
        │◄────── {type:"ping"} ──────────│
        │── {type:"pong"} ─────────────►│
        │                                  │
        │── {type:"status", ...} ───────►│ actualizar painel de estado
        │── {type:"task_update", ...} ───►│ actualizar lista de tarefas
        │── {type:"trading_alert", ...} ─►│ notificação de trading
```

---

## 2. Componentes em Detalhe

### 2.1 nexus-core (`nexus/main.py`)

Ponto de entrada principal. Implementa dois modos de arranque:

```
MODO COMPLETO (quando nexus.api.rest.main + Orchestrator estão disponíveis)
  └─ nexus.api.rest.main:app    (FastAPI com todos os endpoints)
  └─ Orchestrator               (coordena módulos)
  └─ 14 módulos registados dinamicamente
  └─ WS em thread daemon com asyncio.new_event_loop()

MODO MÍNIMO (fallback quando módulos não estão disponíveis)
  └─ FastAPI inline com /health + /status + /ws
  └─ WebSocket inline (heartbeat a cada 30s)
  └─ Não requer nenhuma dependência interna
```

**Razão do WebSocket em thread separada:**  
O `asyncio.gather()` com `uvicorn` pode cancelar ou nunca escalonar tasks concorrentes em Python 3.11+. Isolar o WS num `threading.Thread` com `asyncio.new_event_loop()` garante que a porta 8801 abre independentemente do event loop do uvicorn.

### 2.2 nexus-api (`nexus/api/rest/main.py`)

REST API completa com 30+ endpoints:

| Grupo | Endpoints | Auth |
|-------|-----------|------|
| Health | `GET /health`, `GET /status` | `/health` público |
| **Chat** | `POST /chat` | **sem auth** (design intencional) |
| Memory | `GET/DELETE /memory` | Bearer token |
| Tasks | `GET/POST /tasks`, approve, delete | Bearer token |
| Trading XTB | `/trading/xtb/*` | Bearer token |
| Trading IBKR | `/trading/ibkr/*` | Bearer token |
| Learning | `/learning/multi`, `/synthesize` | Bearer token |
| Evolution | `/evolution/*` | Bearer token |
| Security | `/security/*` | `/pin/verify` público |
| Monitor | `/monitor/metrics` | Bearer token |
| Logs | `/logs/{service}` | Bearer token |
| Settings | `GET/PUT /settings` | Bearer token |
| WebSocket | `WS /ws` | — |

**CORS**: `allow_origins=["*"]`, `allow_credentials=False` (spec: wildcard incompatível com credentials).

**Autenticação**: `HTTPBearer` com `NEXUS_API_KEY` env var. Fallback via `SecurityManager.verify_token()` (JWT).

### 2.3 nexus-dashboard (`nexus/dashboard/server.py`)

Dois papéis em simultaneâneo:

1. **SPA server**: serve `frontend/dist/` com cache correcta
   - `index.html`: `Cache-Control: no-cache, no-store, must-revalidate` (garante bundle fresco após rebuild)
   - `assets/*`: `Cache-Control: public, max-age=31536000, immutable` (hash no nome = seguro)

2. **Reverse proxy**: `/api/{path}` → `http://localhost:8000/{path}` via `httpx.AsyncClient`
   - Transparente (headers, body, método, query params)
   - Timeout: 60s
   - Tratamento explícito de `ConnectError` (503) e outros erros (502)

### 2.4 Frontend React (`nexus/dashboard/frontend/`)

| Ficheiro | Função |
|---|---|
| `src/App.tsx` | Layout principal. `<main className="flex-1 min-h-0">` crítico para scroll em flex |
| `src/api.ts` | `BASE` = `VITE_API_URL` ÷ fallback `localhost:8000`. `wsUrl()` = `VITE_WS_URL` ÷ porta 8801 |
| `src/components/Chat.tsx` | Chat UI com TTS/STT, selector de modo, bubbles com `break-words` |
| `src/components/Avatar.tsx` | Avatar animado com tamanhos por inline `style={{}}` (evita purge JIT) |
| `src/components/Sidebar.tsx` | Navegação. Logo responsivo `min(160px, 20vw)` |

**Build**: Vite injeta `VITE_*` vars em build-time (não runtime). Sem `.env` correcto, o bundle usa fallback `localhost` — o utilizador não consegue ligar.

### 2.5 Módulos do Orquestrador

| Módulo | Path | Função |
|--------|------|---------|
| `memory` | `nexus.core.memory.memory` | Histórico de conversações |
| `personality` | `nexus.core.personality.personality` | Personalidade e contexto do NEXUS |
| `security` | `nexus.core.security.security` | JWT, PIN, rate limiting, audit log |
| `tts` | `nexus.core.voice.tts` | Text-to-Speech (gTTS) |
| `stt` | `nexus.core.voice.stt` | Speech-to-Text com wake word |
| `ml` | `nexus.modules.ml.ml` | Machine Learning local |
| `watchdog` | `nexus.modules.watchdog.watchdog` | Monitorização interna |
| `tasks` | `nexus.modules.tasks.tasks` | Gestão de tarefas com aprovação |
| `learning` | `nexus.modules.learning.learning` | Multi-LLM query + síntese |
| `trading` | `nexus.modules.trading.trading` | Coordenação XTB + IBKR |
| `xtb` | `nexus.modules.trading.xtb.xtb_client` | Integração XTB API |
| `ibkr` | `nexus.modules.trading.ibkr.ibkr_client` | Integração Interactive Brokers |
| `evolution` | `nexus.modules.evolution.evolution` | Auto-melhoria do sistema |
| `truth_checker` | `nexus.modules.truth_checker.truth_checker` | Verificação de factos |
| `video_analysis` | `nexus.modules.video_analysis.video_analysis` | Análise de vídeo/YouTube |
| `scheduler` | `nexus.services.scheduler.scheduler` | Tarefas agendadas |

Todos os módulos são carregados com try/except individual — a falha de um não impede o arranque dos restantes.

---

## 3. Arranque do Sistema

### 3.1 Sequência de Arranque (nexus-core)

```
nexus.main.__main__
  │
  ├─ [1] sys.path auto-fix (/opt/nexus adicionado ao PYTHONPATH)
  ├─ [2] load_dotenv(/opt/nexus/.env)
  ├─ [3] tentar import nexus.api.rest.main + Orchestrator
  │    ├─ sucesso → MODO COMPLETO
  │    └─ falha   → MODO MÍNIMO (FastAPI inline)
  ├─ [4] _launch_ws_thread()
  │    └─ threading.Thread(daemon=True, loop=new_event_loop)
  │         ├─ tentar nexus.ws_server.start_ws(host, port)
  │         └─ fallback: websockets.serve(inline) se ws_server falhar
  ├─ [5] (modo completo) Orchestrator()
  │    └─ registar 14+ módulos individualmente
  ├─ [6] uvicorn.Config + uvicorn.Server
  └─ [7] asyncio.gather(nexus.start(), server.serve())
```

### 3.2 Sequência de Arranque (systemd)

```
systemd
  ├─ nexus-core.service    → python /opt/nexus/nexus/main.py
  ├─ nexus-api.service     → uvicorn nexus.api.rest.main:app --port 8001
  ├─ nexus-dashboard.service → uvicorn nexus.dashboard.server:app --port 9000
  └─ nexus-ws.service      → python /opt/nexus/nexus/ws_server.py (standalone)
```

### 3.3 Dependências de Arranque

```
nexus-dashboard não depende de nexus-core para arrancar.
  └─ Se nexus-core estiver em baixo, dashboard mostra /api/* como 503
  └─ Se dist/ não existir, dashboard devolve {"error": "frontend_not_built"}

nexus-api é autónomo.
  └─ /chat responde com mensagem informativa quando nexus=None

nexus-ws é autónomo.
  └─ O dashboard tenta ligar em ws://VPS:8801
  └─ Se falhar, reconnect automático com backoff
```

---

## 4. Arquitectura do VPS

### 4.1 Estrutura de Pastas

```
/opt/nexus/                         ← NEXUS_HOME
├── .env                           ← variáveis de ambiente (modo 640)
├── .env.local                      ← overrides locais (modo 640)
├── venv/                          ← Python virtual environment
│   └── bin/python, pip, uvicorn
├── logs/                          ← logs persistentes
│   ├── deploy.log                 ← histórico de deploys + health checks
│   └── security.log               ← auditorias de segurança
└── nexus/                         ← código-fonte (git repo)
    ├── __init__.py
    ├── main.py                    ← entry point nexus-core
    ├── ws_server.py               ← WebSocket standalone
    ├── requirements.txt
    ├── .env.example
    ├── api/
    │   ├── rest/main.py           ← FastAPI REST API
    │   └── websocket/ws.py        ← WS endpoint + ConnectionManager
    ├── core/
    │   ├── orchestrator/
    │   ├── memory/
    │   ├── personality/
    │   ├── security/
    │   └── voice/ (tts, stt)
    ├── modules/
    │   ├── ml/, tasks/, learning/
    │   ├── trading/ (xtb/, ibkr/)
    │   ├── evolution/, truth_checker/
    │   └── video_analysis/, watchdog/
    ├── services/
    │   ├── scheduler/
    │   └── logger/
    ├── dashboard/
    │   ├── server.py              ← FastAPI SPA + proxy
    │   └── frontend/
    │       ├── src/ (React + TS)
    │       ├── .env                ← VITE_API_URL + VITE_WS_URL
    │       ├── .env.local          ← sobrepõe .env (mesmo conteúdo)
    │       └── dist/               ← bundle compilado (não em git)
    ├── config/
    ├── docker/
    ├── docs/
    └── scripts/
        ├── install.sh             ← instalação inicial
        ├── deploy_vps.sh          ← executado pelo GitHub Actions
        ├── health_check.sh        ← verifica serviços + portas + HTTP
        ├── rollback.sh            ← git checkout HEAD~N + restart
        ├── security_audit.sh      ← auditoria mensal de segurança
        ├── rebuild_dashboard.sh   ← escreve .env + npm build + restart
        ├── nexus_fix.sh           ← reparação de emergência
        └── nexus_ws_fix.sh        ← recria nexus-ws.service
```

### 4.2 Serviços systemd

| Serviço | Comando | Porta(s) | Restart |
|---------|---------|----------|--------|
| `nexus-core` | `python nexus/main.py` | 8000 + 8801 | `always` |
| `nexus-api` | `uvicorn nexus.api.rest.main:app --port 8001` | 8001 | `always` |
| `nexus-dashboard` | `uvicorn nexus.dashboard.server:app --port 9000` | 9000 | `always` |
| `nexus-ws` | `python nexus/ws_server.py` | 8801 | `always` |

Todos os serviços correm com `PYTHONPATH=/opt/nexus` e `EnvironmentFile=/opt/nexus/.env`.

### 4.3 Scripts de Operação

| Script | Uso | Quando executar |
|--------|-----|------------------|
| `deploy_vps.sh` | `bash deploy_vps.sh <commit_sha>` | Chamado pelo GitHub Actions |
| `health_check.sh` | `bash health_check.sh` | Após deploy, agendado semanal |
| `rollback.sh` | `bash rollback.sh [auto\|manual] N [motivo]` | Auto pelo CI ou manual |
| `rebuild_dashboard.sh` | `bash rebuild_dashboard.sh <VPS_IP>` | Após deploy ou manualmente |
| `security_audit.sh` | `bash security_audit.sh` | Mensal via CI |
| `nexus_fix.sh` | `bash nexus_fix.sh` | Reparação de emergência |
| `nexus_ws_fix.sh` | `bash nexus_ws_fix.sh` | Se porta 8801 não abre |

### 4.4 Porquê Estas Portas

| Porta | Razão |
|-------|--------|
| 9000 | Port acima de 1024 (sem sudo), não conflitua com portas comuns de dev |
| 8000 | Convencão FastAPI/uvicorn (padrão da framework) |
| 8001 | Instância secundária da mesma API (8000+1) |
| 8801 | WebSocket do core (8000 + 801, evita conflito com port 8001 da API) |

---

## 5. Arquitectura CI/CD

### 5.1 Diagrama de Workflows

```
GitHub Events
  │
  ├─ push → claude/create-test-file-d1AY6
  │    ├─► deploy.yml ──────► [test] ─► [deploy] ─► [health-check]
  │    │                               └─ (se falhar) ─► [auto-rollback]
  │    └─► static-analysis.yml ─► [python-lint] + [frontend-lint]
  │
  ├─ pull_request
  │    └─► static-analysis.yml
  │
  ├─ schedule: toda 2ª às 08:00 UTC
  │    └─► weekly-health-audit.yml ─► health_check.sh ─► artefacto Markdown
  │
  ├─ schedule: dia 1 às 09:00 UTC
  │    └─► dependency-update.yml ─► pip upgrade + npm update ─► PR automático
  │
  ├─ schedule: dia 1 às 10:00 UTC
  │    └─► security-audit.yml ─► VPS audit + npm audit + safety
  │
  └─ workflow_dispatch
       └─► rollback-manual.yml ─► rollback.sh manual N motivo
```

### 5.2 Pipeline de Deploy em Detalhe

```
[test]
  ├─ pytest tests/ -v --tb=short
  │    ├─ test_structure.py  : 7 testes (ficheiros, sintaxe Python, CORS, auth)
  │    └─ test_deploy_scripts.py : 5 testes (bash, porta 8801, .env files)
  └─ npx tsc --noEmit
       └─ verifica tipos TypeScript sem compilar
  └── BLOQUEANTE: se falhar, deploy não corre

[deploy] (só se [test] passou)
  └─ SSH → deploy_vps.sh <sha>
       ├─ git fetch + reset --hard origin/branch
       ├─ systemctl restart nexus-core
       ├─ systemctl restart nexus-api
       └─ rebuild_dashboard.sh 35.241.151.115
            ├─ escreve .env + .env.local com VITE_API_URL + VITE_WS_URL
            ├─ rm -rf dist/ + npm install + npm run build
            └─ verifica IP e porta 8801 no bundle

[health-check] (10s após deploy)
  └─ SSH → health_check.sh
       ├─ systemctl is-active nexus-core/api/dashboard/ws
       ├─ ss -tulpn | grep :8000/:8001/:8801/:9000
       ├─ curl http://localhost:8000/health → JSON com "status"
       └─ curl http://localhost:9000/ → <!doctype html>
  └── Se exit code != 0 → dispara auto-rollback

[auto-rollback] (só se deploy falhar)
  └─ SSH → rollback.sh auto 1
       ├─ git checkout HEAD~1 -- .
       ├─ systemctl restart nexus-core/api/dashboard
       └─ health_check.sh (validação pós-rollback)
```

### 5.3 Condições de Rollback

| Situação | Rollback | Tipo |
|-----------|----------|------|
| Deploy SSH falha | Sim | Auto (job `rollback`) |
| `health_check.sh` exit 1 | Sim | Auto (job `rollback`) |
| Testes falham | Não | Deploy não corre |
| Análise estática falha | Não | Só warning (advisory) |
| Utilizador clica Manual Rollback | Sim | Manual (workflow_dispatch) |

### 5.4 Auditorias Automáticas

| Workflow | Frequência | Ferramentas | Artefacto |
|----------|-----------|-------------|----------|
| `weekly-health-audit` | Semanal (2ª) | `health_check.sh` | `health-report-N` (90d) |
| `static-analysis` | Cada push + PR | flake8, black, mypy, tsc, eslint | Job summary |
| `security-audit` | Mensal (dia 1) | `security_audit.sh`, `safety`, `npm audit` | `security-report-N` (365d) |
| `dependency-update` | Mensal (dia 1) | pip, npm, pytest | PR automático |

---

## 6. Arquitectura de Segurança

### 6.1 Pontos de Entrada

```
Internet
  │
  ├─ :9000 (HTTP) ───► nexus-dashboard
  │    └─ SPA React (público)
  │    └─ /api/* → proxy → nexus-core :8000
  │         └─ /chat : SEM AUTH (design intencional)
  │         └─ /health : SEM AUTH
  │         └─ /security/pin/verify : SEM AUTH
  │         └─ todos os outros : Bearer token
  │
  ├─ :8801 (WS)  ───► nexus-ws / nexus-core
  │    └─ aceita qualquer ligação (sem auth WS nativa)
  │    └─ dados enviados são read-only (status, eventos)
  │
  ├─ :8000 (HTTP) ──► nexus-core REST API
  │    └─ devería estar bloqueado por firewall (só acessível via proxy :9000)
  │
  └─ :8001 (HTTP) ──► nexus-api REST API
       └─ mesma situação que :8000
```

### 6.2 Autenticação

```
Fluxo normal:
  1. POST /security/pin/verify {"pin": "..."}
     └─ SecurityManager.verify_pin() + rate limit (5 tentativas/60s)
     └─ → {"ok": true, "token": "jwt_..."}  ou  {"ok": false}
  2. Bearer <token> em todos os endpoints protegidos
     └─ _auth() verifica NEXUS_API_KEY  OU  SecurityManager.verify_token()

Fallback sem Orchestrator:
  └─ NEXUS_API_KEY via env var (default inseguro: "nexus-change-me")
```

### 6.3 Variáveis de Ambiente

| Variável | Ficheiro | Sensibilidade | Notas |
|----------|---------|---------------|-------|
| `NEXUS_API_KEY` | `/opt/nexus/.env` | ALTA | Chave de acesso à API. Mudar do default! |
| `VPS_SSH_KEY` | GitHub Secrets | CRÍTICA | Chave privada SSH. Nunca em git. |
| `VPS_HOST` | GitHub Secrets | MÉDIA | IP do VPS |
| `VPS_USER` | GitHub Secrets | MÉDIA | Utilizador SSH |
| `VITE_API_URL` | `frontend/.env` + `.env.local` | BAIXA | URL pública — visível no bundle |
| `VITE_WS_URL` | `frontend/.env` + `.env.local` | BAIXA | URL pública — visível no bundle |
| `API_PORT` | `/opt/nexus/.env` | BAIXA | Default: 8000 |
| `WS_PORT` | `/opt/nexus/.env` | BAIXA | Default: 8801 |
| `LOG_DIR` | `/opt/nexus/.env` | BAIXA | Default: /var/log/nexus |

### 6.4 Hardening Implementado

| Medida | Estado | Verificado por |
|--------|--------|-----------------|
| `.env` com permissões 640 | `security_audit.sh` corrige automaticamente | Audit mensal |
| CORS `allow_credentials=False` com wildcard | Código (spec CORS) | Teste `test_cors_configured_correctly` |
| Rate limiting no PIN verify (5/60s) | `SecurityManager` | — |
| JWT assinado para sessões | `SecurityManager.generate_token()` | — |
| WebSocket sem credenciais (read-only push) | Design | — |
| Logs de auditoria | `SecurityManager.get_audit_log()` | — |
| Credenciais default detectadas | `security_audit.sh` | Audit mensal |
| Pacotes desactualizados | `safety` + `npm audit` | Audit mensal |

### 6.5 Recomendações de Melhoria

| Prioridade | Recomendação | Impacto |
|-----------|--------------|--------|
| **ALTA** | Bloquear portas 8000 e 8001 via `ufw` — só :9000 e :8801 devem ser públicas | Impede acesso directo à API sem proxy |
| **ALTA** | Mudar `NEXUS_API_KEY` do valor default `nexus-change-me` | Evita acesso não autorizado |
| **MÉDIA** | Adicionar autenticação WebSocket (token no URL ou header) | O WS actual aceita qualquer ligação |
| **MÉDIA** | Activar `PasswordAuthentication no` no sshd | Uso exclusivo de chaves SSH |
| **MÉDIA** | HTTPS via Let's Encrypt + nginx como reverse proxy | Encripta tráfego :9000 |
| **BAIXA** | Mover `NEXUS_API_KEY` para HashiCorp Vault ou GitHub Secrets no deploy | Elimina secret em ficheiro |
| **BAIXA** | Adicionar CSP headers no dashboard (Content-Security-Policy) | Protecção XSS |

---

## 7. Escalabilidade

### 7.1 Estado Actual

```
┌──────────────────────────────────────┐
│    VPS Único (single node)            │
│                                      │
│  nexus-dashboard :9000               │
│  nexus-core      :8000               │
│  nexus-api       :8001               │
│  nexus-ws        :8801               │
│                                      │
│  Armazenamento: ficheiros locais     │
│  Estado: em memória (sem persist.)   │
│  Sessions: sem sticky sessions       │
└──────────────────────────────────────┘
```

**O que já existe que facilita escalar:**
- Serviços independentes (cada um pode ser movido)
- Proxy em `dashboard/server.py` (ponto de entrada único)
- Módulos carregados dinamicamente (fáceis de isolar)
- `nexus-api` completamente autónoma
- Docker já preparado (`nexus/docker/`)

**O que limita a escalabilidade actual:**
- Estado do Orchestrator em memória (sem Redis/DB)
- WebSocket sem pub/sub (broadcast directo, 1 instância)
- Memory module sem backend persistente partilhado
- Ficheiro `.env` local (não centralizado)

### 7.2 Proposta de Evolução Multi-Instância

```
                        ┌─────────────────────┐
                        │  nginx / Caddy           │
                        │  HTTPS :443               │
                        │  reverse proxy           │
                        └─────────────────────┘
                              │         │
              ┌────────────┘         └────────────┐
              ▼                              ▼
┌────────────────────┐  ┌────────────────────┐
│  nexus-dashboard[1]  │  │  nexus-dashboard[2]  │
│  (CDN / static)      │  │  (CDN / static)      │
└────────────────────┘  └────────────────────┘
        │  /api/*                     │  /api/*
        ▼                             ▼
┌───────────────────────────────────────────────┐
│           Load Balancer (HAProxy / nginx)       │
└───────────────────────────────────────────────┘
              │              │
     ┌─────────┘   ┌─────────┘
     ▼                   ▼
┌─────────────┐   ┌─────────────┐
│ nexus-api[1]│   │ nexus-api[2]│  (stateless, escala horizontal)
└─────────────┘   └─────────────┘
              │              │
              └─────▼─────┘
        ┌────────────────────────────────────┐
        │  nexus-core (1 instância)             │
        │  Orchestrator + módulos              │
        └────────────────────────────────────┘
              │         │
     ┌─────────┘   ┌─────────┘
     ▼                   ▼
┌────────────┐   ┌────────────┐
│ Redis (WS  │   │ PostgreSQL  │  (a adicionar para estado partilhado)
│ pub/sub)   │   │ (memory,    │
└────────────┘   │ tasks, logs)│
                  └────────────┘
```

### 7.3 Roadmap de Escalabilidade

| Fase | Acção | Pré-requisito |
|------|-------|---------------|
| **1 — Imediata** | Activar `ufw`, HTTPS via Caddy, nginx como proxy | nenhum |
| **2 — Curto prazo** | Adicionar Redis para WS pub/sub | Redis no VPS |
| **2 — Curto prazo** | SQLite/PostgreSQL para Memory module | Schema migration |
| **3 — Médio prazo** | Docker Compose com todos os serviços | `nexus/docker/` já existe |
| **3 — Médio prazo** | `nexus-api` em múltiplas instâncias (stateless) | Load balancer |
| **4 — Longo prazo** | Kubernetes / GKE para auto-scaling | Container registry |
| **4 — Longo prazo** | Separar `nexus-core` em microserviços | Refactoring dos módulos |

### 7.4 Componentes Já Prontos para Escalar

| Componente | Estado | Razão |
|---|---|---|
| `nexus-dashboard` | Pronto | Apenas serve ficheiros estáticos + proxy |
| `nexus-api` | Pronto | Stateless quando `_nexus=None` (modo fallback) |
| `nexus-ws` | Parcial | Sem pub/sub — só 1 instância possivel |
| `nexus-core` | Não pronto | Estado em memória, 1 Orchestrator por processo |
| CI/CD | Pronto | Workflows são VPS-agnosósticos (SSH genérico) |

---

## Referências Rápidas

```bash
# Ver estado do sistema
sudo systemctl status nexus-core nexus-api nexus-dashboard nexus-ws

# Ver logs de deploy
tail -100 /opt/nexus/logs/deploy.log

# Health check manual
bash /opt/nexus/nexus/scripts/health_check.sh

# Rollback manual (1 commit)
bash /opt/nexus/nexus/scripts/rollback.sh manual 1 "motivo"

# Rebuild do dashboard
bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh 35.241.151.115

# Reparação de emergência
bash /opt/nexus/nexus/scripts/nexus_fix.sh

# Auditoria de segurança
bash /opt/nexus/nexus/scripts/security_audit.sh
```
