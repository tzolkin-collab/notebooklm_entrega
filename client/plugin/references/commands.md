# Referencia de Comandos — NotebookLM

> O endereco do servidor aparece escrito neste arquivo porque a skill nao le
> variavel de ambiente. Se o servidor mudar de host, troque aqui, no `SKILL.md`
> e no `plugin.json`, e reempacote o `.skill`.

Ha dois caminhos: o **conector MCP** (preferencial, no Claude) e a **API REST** (n8n/automacoes).

---

## 1. Conector MCP (ferramentas nativas no Claude)

Disponiveis apos vincular o conector (OAuth). O usuario e identificado pelo login Google.

| Ferramenta | O que faz |
|---|---|
| `quem_sou_eu()` | Email, nivel e se ha token NotebookLM ativo |
| `listar_notebooks()` | Notebooks acessiveis ao usuario |
| `perguntar(notebook_id, pergunta)` | Consulta com resposta + citacoes |
| `listar_fontes(notebook_id)` | Fontes indexadas do notebook |
| `verificar_token()` | Testa via rede se o token Google ainda vale |

Adicionar o conector (uma vez): Settings -> Connectors -> Add custom connector ->
URL `https://connectors-notebooklm.tpgavy.easypanel.host/mcp` -> Vincular -> Continuar com Google.

---

## 2. API REST (n8n / automacoes)

Base: `https://connectors-notebooklm.tpgavy.easypanel.host/api`
Auth: `Authorization: Bearer <token-do-usuário>` — o nível vem do token.
O token sai do onboarding admin (POST /admin/users) ou de `gen_token.py`.

### Consultar (ask)
```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "<pergunta>"}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/notebooks/<id>/ask
```

### Listar notebooks
```bash
curl -H "Authorization: Bearer <token>" \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/notebooks
```

### Listar fontes
```bash
curl -H "Authorization: Bearer <token>" \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/notebooks/<id>/sources
```

### Adicionar fonte (gestor+)
```bash
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '{"url": "<url>"}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/notebooks/<id>/sources
```

### Criar notebook (admin)
```bash
curl -X POST -H "Authorization: Bearer <token_admin>" \
  -H "Content-Type: application/json" -d '{"title": "<nome>"}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/notebooks
```

### Verificar token / status da equipe
```bash
curl -H "Authorization: Bearer <token>" \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/auth/check

# equipe (admin)
curl -H "Authorization: Bearer <token_admin>" \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/team
```

### Ativar usuário / emitir token (admin)
```bash
curl -X POST -H "Authorization: Bearer <token_admin>" \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","nivel":"juridico","ativo":true}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/admin/users
# -> resposta contém o api_token Bearer do usuário
```

---

## 3. Gestao de token

```bash
# Onboarding self-service (login + upload; entra PENDENTE) — máquina do usuário
python connect.py --email pessoa@escritorio.com --nome "Nome"

# Renovar token expirado — re-roda connect.py (não mexe no nível/ativação)
notebooklm --profile <profile> auth refresh           # tenta refresh silencioso
python connect.py --email <email> --nome "<Nome>"     # re-sobe o token cifrado

# Bootstrap do token Bearer do 1º admin (break-glass, no servidor/máquina confiável)
python server/db/gen_token.py --email <email_admin>
```

> Ferramentas que tocam a chave Fernet (`server/db/register.py`, `check.py`) são
> **break-glass de admin** — nunca rodam em máquina de usuário final.

Niveis: `admin`, `gestor`, `juridico`, `financeiro`.

---

## Codigos de resposta (REST)

| Codigo | Significado |
|---|---|
| 200 | Sucesso |
| 401 | Token de usuário inválido ou inativo (Bearer) |
| 403 | Nível insuficiente, ou connector key inválida (`/token/upload`) |
| 404 | Usuário não encontrado (ativação antes de connect.py) |
| 500 | Erro interno (token expirado, falha no NotebookLM) |
