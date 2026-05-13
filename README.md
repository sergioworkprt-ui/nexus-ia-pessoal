# NEXUS IA Pessoal — Versão Pro

## Estrutura de ficheiros

```
nexus-pro/
├── app.py                  ← Servidor principal
├── requirements.txt        ← Dependências Python
├── Procfile               ← Comando de arranque
├── modules/
│   ├── __init__.py
│   ├── database.py        ← Base de dados SQLite
│   ├── ai_router.py       ← Router de IAs gratuitas
│   ├── scheduler.py       ← Tarefas agendadas 24/7
│   ├── enricher.py        ← YouTube + pesquisa web
│   ├── email_sender.py    ← Notificações Gmail
│   ├── file_handler.py    ← Upload/análise de PDFs
│   ├── notifications.py   ← Notificações internas
│   ├── reporter.py        ← Relatórios automáticos
│   └── youtube.py         ← Wrapper YouTube
└── static/
    ├── index.html         ← Interface web
    ├── manifest.json      ← PWA manifest
    ├── sw.js              ← Service Worker
    ├── icon-192.png       ← Ícone app
    └── icon-512.png       ← Ícone app grande
```

---

## Variáveis de ambiente (Render → Environment) 

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ADMIN_PASSWORD` | ✅ | Password de login |
| `SECRET_KEY` | ✅ | Chave de sessão (qualquer texto longo) |
| `GEMINI_API_KEY` | ✅ | Google Gemini (aistudio.google.com) |
| `GROQ_API_KEY` | ✅ | Groq (console.groq.com) |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter (openrouter.ai) |
| `CEREBRAS_API_KEY` | ⚡ | Cerebras (cloud.cerebras.ai) |
| `MISTRAL_API_KEY` | ⚡ | Mistral (console.mistral.ai) |
| `SERPER_API_KEY` | ⚡ | Pesquisa web (serper.dev) |
| `GMAIL_ADDRESS` | ⚡ | Email de envio |
| `GMAIL_APP_PASSWORD` | ⚡ | App Password Gmail |
| `RESET_TOKEN` | 🔒 | Token de reset de emergência |

---

## Como instalar no Render

1. Faz upload de todos os ficheiros para o GitHub
2. Cria novo Web Service no Render ligado ao repo
3. Render deteta o Procfile automaticamente
4. Adiciona todas as variáveis de ambiente
5. Confirma que o Disk está montado em `/data`
6. Clica Deploy

---

## Como atualizar

1. Edita o ficheiro no GitHub
2. Render faz redeploy automático em ~2 minutos
3. Para forçar: Render → Manual Deploy → Deploy latest

---

## Como reiniciar com segurança

1. Render → Manual Deploy → Deploy latest
2. O estado é preservado em `/data/nexus.db`
3. O scheduler reinicia automaticamente
4. As sessões de login são mantidas

---

## Como recuperar estado após crash

O estado está em `/data/nexus.db` (disco persistente).
Em caso de corrupção:
```
https://teu-url.onrender.com/reset/nexus-reset-2024
```
⚠️ Isto apaga TUDO. Muda o RESET_TOKEN nas variáveis!

---

## Modo Free vs Modo Pago

| Funcionalidade | Free | Pago (Starter $7/mês) |
|---|---|---|
| Chat com IA | ✅ | ✅ |
| YouTube + pesquisa | ✅ | ✅ |
| Email automático | ✅ | ✅ |
| Base de dados | ⚠️ Reinicia | ✅ Persistente |
| Scheduler 24/7 | ❌ | ✅ |
| Uploads grandes | ❌ | ✅ |
| Logs persistentes | ❌ | ✅ |
| Sempre ligado | ❌ | ✅ |

A NEXUS deteta automaticamente o modo e adapta o comportamento.

---

## Endpoints principais

| Endpoint | Método | Descrição |
|---|---|---|
| `/api/login` | POST | Login |
| `/api/logout` | POST | Logout |
| `/api/me` | GET | Info do utilizador + modo |
| `/api/chat` | POST | Chat com IA |
| `/api/history` | GET | Histórico de conversas |
| `/api/memory` | GET/POST | Memória persistente |
| `/api/tasks` | GET/POST | Gestão de tarefas |
| `/api/schedule` | GET/POST | Tarefas agendadas |
| `/api/upload` | POST | Upload de ficheiros |
| `/api/stats` | GET | Estatísticas |
| `/api/report` | POST | Gerar relatório |
| `/api/heartbeat` | GET | Keep-alive + scheduler |
| `/api/logs` | GET | Logs do servidor |

---

## Como usar cada função

### Chat simples
Escreve qualquer mensagem no chat.

### Analisar YouTube
Cola links do YouTube — a NEXUS extrai a transcrição automaticamente.

### Pesquisa web
Escreve "pesquisa [tema]" — a NEXUS pesquisa e resume.

### Agendar tarefa
```json
POST /api/schedule
{
  "title": "Relatório diário",
  "prompt": "Cria um resumo das minhas tarefas",
  "run_at": "2026-04-27T08:00:00",
  "email": "sergio@gmail.com"
}
```

### Análise de PDF
Clica no botão 📄 e seleciona o ficheiro.

### Relatório automático
```json
POST /api/report
{"type": "daily"}
```
Types: `daily`, `weekly`, `monthly`

---

## Segurança

- Login com password + sessão de 30 dias
- PIN de autorização para ações sensíveis
- Impressão digital via WebAuthn (telemóvel)
- Todas as rotas protegidas por `@login_required`
- RESET_TOKEN para emergências

---

## Suporte e melhorias futuras 

Quando tiveres orçamento adicional:
- Whisper API (transcrição de áudio real)
- Base de dados PostgreSQL (mais robusta)
- Redis para filas de tarefas
- Múltiplos utilizadores
- Dashboard analytics avançado
