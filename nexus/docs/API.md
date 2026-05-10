# NEXUS — Referência da API REST

Base URL: `http://localhost:8000`

Todos os endpoints (excepto `/health`) requerem header:
```
Authorization: Bearer <token>
```

---

## GET /health

Verifica se a API está online. Não requer autenticação.

**Resposta:**
```json
{"status": "ok", "version": "1.0.0"}
```

---

## POST /chat

Envia mensagem ao NEXUS.

**Body:**
```json
{"message": "Qual é o preço do EURUSD?"}
```

**Resposta:**
```json
{"response": "O EURUSD está a 1.0821.", "source": "personality"}
```

---

## GET /status

Estado do sistema e módulos.

**Resposta:**
```json
{
  "name": "NEXUS",
  "version": "1.0.0",
  "modules": {"trading": "running", "ml": "running"},
  "trading_mode": "simulation"
}
```

---

## POST /trade

Coloca uma ordem de trading.

**Body:**
```json
{
  "symbol": "EURUSD",
  "side": "BUY",
  "size": 0.01,
  "stop_loss": 1.0750,
  "take_profit": 1.0900
}
```

---

## GET /positions

Lista posições abertas.

**Resposta:**
```json
{
  "positions": [
    {
      "symbol": "EURUSD",
      "side": "BUY",
      "size": 0.01,
      "entry_price": 1.0821,
      "current_price": 1.0835,
      "pnl": 1.40,
      "broker": "xtb"
    }
  ]
}
```

---

## POST /trade/real/enable

Activa o modo de trading real. Requer confirmação manual.

**Resposta:**
```json
{"status": "real_mode_enabled", "warning": "Real money at risk"}
```

---

## GET /memory

Devolve as últimas 50 entradas de memória.

---

## WebSocket /ws

Ligação em tempo real para estado do avatar e eventos do sistema.

**Mensagem recebida:**
```json
{"avatar_state": "speaking", "event": "tts_start", "ts": 1700000000}
```
