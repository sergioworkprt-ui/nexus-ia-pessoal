# NEXUS — Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                        NEXUS                            │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌────────────────────┐  │
│  │Orchestrat│──▶│ Memory   │   │  Security Manager  │  │
│  │   or     │   │          │   │  (JWT + audit log) │  │
│  └────┬─────┘   └──────────┘   └────────────────────┘  │
│       │                                                 │
│  ┌────▼──────────────────────────────────────────────┐  │
│  │                    Módulos                         │  │
│  │  Personality  │  TTS/STT  │  Avatar               │  │
│  │  Trading      │  ML       │  Watchdog │ Scheduler  │  │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  ┌──────────────────┐   ┌──────────────────────────┐   │
│  │   REST API       │   │    WebSocket              │   │
│  │   FastAPI/8000   │   │    /ws  (avatar state)    │   │
│  └──────────────────┘   └──────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
         │                        │
   ┌─────▼──────┐         ┌───────▼──────┐
   │  Dashboard  │         │  Brokers      │
   │  React/3000 │         │  XTB | IBKR   │
   └────────────┘         └──────────────┘
```

## Fluxo de uma mensagem

1. Utilizador envia mensagem via REST (`POST /chat`) ou voz (STT)
2. `Orchestrator.process()` regista na `Memory` e chama `Personality`
3. `Personality` chama o LLM (OpenAI / local) e devolve resposta
4. Resposta é enviada via TTS e WebSocket (`avatar_state: speaking`)
5. Após 3s o avatar volta a `idle`

## Fluxo de uma ordem

1. LLM detecta intenção de trade e chama `TradingModule.execute_order()`
2. `SecurityManager` valida risco (tamanho, exposição, intervalo)
3. Em modo simulação: ordem é registada localmente
4. Em modo real: ordem é enviada ao broker (XTB ou IBKR)
5. Resultado é registado em `Memory` e enviado via WebSocket
