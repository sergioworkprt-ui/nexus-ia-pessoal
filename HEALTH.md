# NEXUS — Monitorização e Saúde do Sistema

## Arquitectura de Serviços

| Serviço | Porta | Processo |
|---------|-------|----------|
| `nexus-core` | 8000 (API) + 8801 (WS) | `uvicorn nexus.main:app` |
| `nexus-api` | 8001 | `uvicorn nexus.api.rest.main:app` |
| `nexus-dashboard` | 9000 | `uvicorn nexus.dashboard.server:app` |

---

## Indicadores Monitorizados

| Indicador | Script | Frequência |
|-----------|--------|------------|
| systemd services activos | `health_check.sh` | Após deploy + semanal |
| Portas TCP abertas | `health_check.sh` | Após deploy + semanal |
| HTTP `/health` (porta 8000) | `health_check.sh` | Após deploy + semanal |
| HTTP dashboard (porta 9000) | `health_check.sh` | Após deploy + semanal |
| Permissões de ficheiros | `security_audit.sh` | Mensal |
| Credenciais default no .env | `security_audit.sh` | Mensal |
| Configuração SSH | `security_audit.sh` | Mensal |
| Pacotes Python desactualizados | `security_audit.sh` | Mensal |
| Actualizações de segurança apt | `security_audit.sh` | Mensal |
| Vulnerabilidades npm | `security-audit.yml` | Mensal |
| Vulnerabilidades Python | `security-audit.yml` | Mensal |

---

## Como Interpretar os Resultados

### health_check.sh

```
✔ verde  — componente OK
✘ vermelho — componente com falha (aumenta FAIL counter)
⚠ amarelo — aviso (não crítico)
```

**Exit code 0** — tudo OK  
**Exit code 1** — pelo menos um componente em falha

Linhas a procurar:
- `INACTIVE` → serviço systemd parado
- `FECHADA` → porta não está a ouvir
- `sem resposta válida` → API não responde a `/health`

### security_audit.sh

**Falhas (✘)** — corrigir imediatamente (ex: credenciais inseguras, serviço parado)  
**Avisos (⚠)** — rever e corrigir quando possível (ex: pacotes desactualizados, ufw inactivo)

### deploy.log

```bash
cat /opt/nexus/logs/deploy.log
tail -200 /opt/nexus/logs/deploy.log
```

Padrões:
- `DEPLOY_STATUS=OK` → deploy bem-sucedido
- `HEALTH_CHECK=PASS` → health check OK
- `HEALTH_CHECK=FAIL` → health check falhou (rollback disparou)
- `ROLLBACK=OK` → rollback aplicado com sucesso
- `ROLLBACK=PARTIAL` → rollback aplicado mas health check pós-rollback falhou
- `SECURITY_AUDIT FAIL=0` → auditoria sem falhas críticas

---

## Ações por Tipo de Falha

### nexus-core INACTIVE

```bash
sudo journalctl -u nexus-core -n 50 --no-pager
sudo systemctl restart nexus-core
# Se falhar repetidamente:
sudo bash /opt/nexus/nexus/scripts/nexus_fix.sh
```

### Porta 8801 (WebSocket) fechada

```bash
systemctl status nexus-core
systemctl status nexus-ws
sudo bash /opt/nexus/nexus/scripts/nexus_ws_fix.sh
```

### Dashboard não devolve HTML (porta 9000)

```bash
ls -la /opt/nexus/nexus/dashboard/frontend/dist/
sudo bash /opt/nexus/nexus/scripts/rebuild_dashboard.sh 35.241.151.115
```

### Deploy falhou + rollback automático

1. Ver o job summary no GitHub Actions
2. Verificar qual step falhou (`deploy` ou `health`)
3. Consultar o log: `tail -100 /opt/nexus/logs/deploy.log`
4. Corrigir e fazer push

### Rollback manual necessário

**Via GitHub Actions** (recomendado):  
Actions → **Manual Rollback** → **Run workflow** → preencher `commits_back` + `reason`

**Via SSH**:
```bash
sudo bash /opt/nexus/nexus/scripts/rollback.sh manual 1 "motivo aqui"
```

### Credenciais default detectadas no .env

```bash
nano /opt/nexus/.env
# Substituir NEXUS_API_KEY=nexus-change-me por um valor seguro
sudo systemctl restart nexus-core nexus-api
```

---

## Workflows Automáticos

| Workflow | Trigger | Função |
|----------|---------|--------|
| **Deploy to VPS** | push → branch | Testes → deploy → health-check |
| **Manual Rollback** | workflow_dispatch | Rollback manual com N commits |
| **Weekly Health Audit** | 2as às 08:00 UTC | Health check + relatório (artefacto 90d) |
| **Static Analysis** | push + PR | flake8 + mypy + tsc + eslint |
| **Monthly Dependency Update** | dia 1 às 09:00 UTC | Actualiza deps + PR automático |
| **Security Audit** | dia 1 às 10:00 UTC | Auditoria VPS + npm audit + safety |

---

## Relatórios e Artefactos

Todos os relatórios são publicados em GitHub Actions → run específico → **Artifacts**:

| Artefacto | Workflow | Retenção |
|-----------|----------|----------|
| `health-report-N` | Weekly Health Audit | 90 dias |
| `security-report-N` | Security Audit | 365 dias |

---

## Logs no VPS

```
/opt/nexus/logs/
  deploy.log     — todos os deploys, health checks e rollbacks
  security.log   — auditorias de segurança
```
