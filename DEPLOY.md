# NEXUS — Guia de Deploy, Rollback e Testes

## Arquitectura de Serviços

| Serviço | Porta | Descrição |
|---------|-------|------------|
| `nexus-core` | 8000 (API) + 8801 (WS) | Orquestrador principal |
| `nexus-api` | 8001 | REST API autónoma |
| `nexus-dashboard` | 9000 | Frontend React/Vite |
| `nexus-ws` | 8801 | WebSocket (gerido pelo core) |

---

## Deploy Automático (GitHub Actions)

Cada push para a branch `claude/create-test-file-d1AY6` dispara o workflow **Deploy to VPS**:

```
push → [1. test] → [2. deploy] → [3. health-check]
                        ↓ (se falhar)
                  [auto-rollback]
```

### Jobs

**1. test** — corre no GitHub runner (não toca no VPS):
- `pytest tests/` — estrutura, sintaxe Python, CORS, /chat sem auth
- `tsc --noEmit` — TypeScript type-check do frontend
- Se qualquer teste falhar, o deploy **não corre**

**2. deploy** — via SSH para o VPS:
- Chama `nexus/scripts/deploy_vps.sh` no VPS
- git reset --hard para o commit exacto do push
- Reinicia `nexus-core` e `nexus-api`
- Rebuilds o dashboard com `rebuild_dashboard.sh`
- Logs gravados em `/opt/nexus/logs/deploy.log`

**3. health-check** — imediatamente após o deploy:
- Verifica serviços systemd activos
- Verifica portas 8000, 8001, 8801, 9000 abertas
- Verifica `GET /health` e `GET /` respondem correctamente
- Se falhar, regista em deploy.log e sai com erro (dispara rollback)

**auto-rollback** — só corre se `deploy` falhar:
- Chama `rollback.sh auto 1` no VPS
- Reverte para `HEAD~1` e reinicia serviços

### Secrets necessários no GitHub

| Secret | Valor |
|--------|-------|
| `VPS_SSH_KEY` | Chave privada SSH (ed25519) |
| `VPS_HOST` | IP do VPS (ex: `35.241.151.115`) |
| `VPS_USER` | Utilizador SSH (ex: `ubuntu`) |

---

## Rollback Manual

### Via GitHub Actions (recomendado)

1. Vai a **Actions → Manual Rollback → Run workflow**
2. Preenche:
   - `commits_back`: quantos commits reverter (default: `1`)
   - `reason`: motivo (para o audit log)
3. Clica **Run workflow**

O workflow chama `rollback.sh manual N motivo` no VPS e mostra o resultado no job summary.

### Via SSH directamente

```bash
# Reverter 1 commit
sudo bash /opt/nexus/nexus/scripts/rollback.sh manual 1 "hotfix urgente"

# Reverter 2 commits
sudo bash /opt/nexus/nexus/scripts/rollback.sh manual 2 "deploy quebrou dashboard"
```

### Ver histórico de deploys

```bash
cat /opt/nexus/logs/deploy.log
```

---

## Testes Locais

### Pré-requisitos

```bash
pip install pytest
bash --version  # >= 4.0
node --version  # >= 18
```

### Correr todos os testes

```bash
# Na raiz do repositório
pytest tests/ -v
```

### Correr testes específicos

```bash
# Apenas estrutura e sintaxe
pytest tests/test_structure.py -v

# Apenas scripts de deploy
pytest tests/test_deploy_scripts.py -v

# TypeScript type-check
cd nexus/dashboard/frontend
npm ci && npx tsc --noEmit
```

### O que os testes verificam

| Ficheiro | Testes |
|----------|--------|
| `test_structure.py` | Ficheiros essenciais existem · Sintaxe Python · requirements.txt · package.json · VITE env vars · CORS · /chat sem auth |
| `test_deploy_scripts.py` | Sintaxe bash · WS porta 8801 · .env/.env.local escritos · rollback.sh usa git · health_check.sh verifica portas |

---

## Adicionar Novas Funcionalidades

1. **Cria um branch** a partir de `claude/create-test-file-d1AY6`
2. **Desenvolve** a funcionalidade
3. **Adiciona testes** em `tests/` se criares novos ficheiros ou endpoints
4. **Faz push** — o workflow de testes corre automaticamente
5. **Faz merge** para `claude/create-test-file-d1AY6` — o deploy corre automaticamente

### Checklist antes de fazer push

```bash
# 1. Testes passam
pytest tests/ -v

# 2. TypeScript compila
cd nexus/dashboard/frontend && npx tsc --noEmit

# 3. Sintaxe bash OK
bash -n nexus/scripts/rebuild_dashboard.sh
bash -n nexus/scripts/rollback.sh
```

---

## Ficheiros Chave

```
.github/workflows/
  deploy.yml              # CI/CD principal
  rollback-manual.yml     # Rollback manual via UI

nexus/scripts/
  deploy_vps.sh           # Executado no VPS pelo GitHub Actions
  health_check.sh         # Verifica serviços e portas
  rollback.sh             # Reverte para commit anterior
  rebuild_dashboard.sh    # Rebuild do frontend React
  install.sh              # Instalação inicial do VPS

tests/
  test_structure.py       # Testes de estrutura e sintaxe
  test_deploy_scripts.py  # Testes dos scripts bash

/opt/nexus/logs/
  deploy.log              # Log persistente de todos os deploys
```
