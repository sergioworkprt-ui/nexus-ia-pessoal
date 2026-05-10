# NEXUS — Referência de Módulos

## Orchestrator (`nexus/core/orchestrator.py`)

Núcleo do sistema. Regista módulos, gere o ciclo de vida e processa mensagens.

- `register(name, module)` — regista um módulo
- `start()` — arranca todos os módulos em paralelo
- `process(text, source)` — processa input de texto ou voz

## Memory (`nexus/core/memory/memory.py`)

Armazena histórico de conversas e contexto persistente em JSON.

## Personality (`nexus/core/personality/personality.py`)

Integração LLM com persona JARVIS/Friday. Fallback sem API key.

- Variável `NEXUS_PERSONA` no `.env`: `JARVIS` (masculino) ou `Friday` (feminino)

## Security (`nexus/core/security/security.py`)

JWT auth, audit log, validação de risco para trading.

- `validate_token(token)` — valida Bearer token
- `validate_trade(size, symbol)` — verifica limites de risco

## TTS (`nexus/core/voice/tts.py`)

Síntese de voz. Suporta pyttsx3, ElevenLabs, Azure.

## STT (`nexus/core/voice/stt.py`)

Reconhecimento de voz com Whisper. Wake word configurável.

## TradingModule (`nexus/modules/trading/trading.py`)

Ordens de trading com suporte a XTB e IBKR.

- Modo simulação por defeito (sem risco real)
- Activar modo real: `POST /trade/real/enable`

## MLModule (`nexus/modules/ml/ml.py`)

Previsões simples de mercado. Extensível com scikit-learn / torch.

## Watchdog (`nexus/modules/watchdog/watchdog.py`)

Monitoriza módulos e reinicia em caso de falha.

## Scheduler (`nexus/services/scheduler/scheduler.py`)

Agenda tarefas periódicas (ex: relatório diário às 08:00).
