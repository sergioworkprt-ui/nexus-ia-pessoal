# NEXUS — Guia de Instalação

## Requisitos

- Ubuntu 22.04 LTS (VPS ou bare-metal)
- 2 GB RAM mínimo (4 GB recomendado)
- 20 GB disco
- Python 3.11+
- Docker + Docker Compose (opcional, para modo contentor)

## Instalação Rápida (VPS)

```bash
# Como root
curl -fsSL https://raw.githubusercontent.com/sergioworkprt-ui/nexus-ia-pessoal/main/nexus/scripts/install.sh | bash
```

O script instala todas as dependências, cria o utilizador `nexus`, clona o repositório e configura os serviços systemd.

## Configuração

Edita `/opt/nexus/.env` com as tuas chaves:

```env
NEXUS_SECRET_KEY=gera-uma-chave-forte
OPENAI_API_KEY=sk-...
XTB_ACCOUNT_ID=...
XTB_PASSWORD=...
```

## Iniciar

```bash
sudo systemctl start nexus-api nexus-core
sudo systemctl status nexus-api nexus-core
```

## Verificar

```bash
curl http://localhost:8000/health
# {"status": "ok", ...}
```

## Instalação com Docker

```bash
cd /opt/nexus/nexus/docker
docker compose up -d
```

## Actualizar

```bash
sudo bash /opt/nexus/nexus/scripts/update.sh
```

## Reparar

```bash
sudo bash /opt/nexus/nexus/scripts/repair.sh
```
