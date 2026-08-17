# Referencia de Comandos — NotebookLM

> `<PUBLIC_URL>` e a URL do servidor da organização. Substitua antes de
> reempacotar o `.skill` — este arquivo nao le variavel de ambiente. Tem que
> bater com o `PUBLIC_URL` do servidor e com o `redirect_uri` registrado no
> Google Cloud Console.

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
URL `<PUBLIC_URL>/mcp` -> Vincular -> Continuar com Google.

---

## 2. API REST (n8n / automacoes)

Base: `<PUBLIC_URL>/api`
Auth: `Authorization: Bearer <token-do-usuário>` — o nível vem do token.
O token sai do onboarding admin (POST /admin/users) ou de `gen_token.py`.

### Consultar (ask)
```bash
curl -X POST \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question": "<pergunta>"}' \
  <PUBLIC_URL>/api/notebooks/<id>/ask
```

### Listar notebooks
```bash
curl -H "Authorization: Bearer <token>" \
  <PUBLIC_URL>/api/notebooks
```

### Listar fontes
```bash
curl -H "Authorization: Bearer <token>" \
  <PUBLIC_URL>/api/notebooks/<id>/sources
```

### Adicionar fonte (gestor+)
```bash
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '{"url": "<url>"}' \
  <PUBLIC_URL>/api/notebooks/<id>/sources
```

### Criar notebook (admin)
```bash
curl -X POST -H "Authorization: Bearer <token_admin>" \
  -H "Content-Type: application/json" -d '{"title": "<nome>"}' \
  <PUBLIC_URL>/api/notebooks
```

### Verificar token / status da equipe
```bash
curl -H "Authorization: Bearer <token>" \
  <PUBLIC_URL>/api/auth/check

# equipe (admin)
curl -H "Authorization: Bearer <token_admin>" \
  <PUBLIC_URL>/api/team
```

### Ativar usuário / emitir token (admin)
```bash
curl -X POST -H "Authorization: Bearer <token_admin>" \
  -H "Content-Type: application/json" \
  -d '{"email":"<email>","nivel":"juridico","ativo":true}' \
  <PUBLIC_URL>/api/admin/users
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
