# NEXUS — Segurança

## Autenticação

Todos os endpoints (excepto `/health`) exigem `Authorization: Bearer <token>`.

O token é gerado com JWT (HS256) e expira em 60 minutos por defeito.

### Obter token

```bash
curl -X POST http://localhost:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"password": "<NEXUS_SECRET_KEY>"}'
```

## Trading — Limites de Risco

| Parâmetro           | Valor padrão |
|---------------------|-------------|
| MAX_ORDER           | 10 €         |
| MAX_EXPOSURE        | 100 €        |
| MIN_ORDER_INTERVAL  | 60 s         |
| MAX_DAILY_LOSS      | 50 €         |

Editar em `nexus/config/trading.yaml`.

## Modo Real

O modo real de trading está **desactivado por defeito**.
Para activar:

```bash
curl -X POST http://localhost:8000/trade/real/enable \
  -H 'Authorization: Bearer <token>'
```

O modo real reinicia para simulação ao reiniciar o serviço.

## Audit Log

Todas as ordens e acções de segurança são registadas em `/var/log/nexus/audit.log`.

## Boas Práticas

- Usa `NEXUS_SECRET_KEY` com 32+ caracteres aleatórios
- Não expões a porta 8000 directamente; usa Nginx com TLS
- Mantém as chaves de broker encriptadas no `.env`
- Faz backup de `/data/nexus/memory.json` regularmente
