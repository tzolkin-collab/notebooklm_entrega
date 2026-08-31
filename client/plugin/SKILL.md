---
name: aaa-notebooklm
description: Skill do NotebookLM (servidor-gerente da organizacao) — consulta notebooks com citacoes, gerencia os tokens Google e diagnostica falhas de autenticacao. Ative sempre que o usuario mencionar "NotebookLM", "notebook", "consulta juridica", "token", "auth", "connector", ou usar /notebook. Ative TAMBEM em qualquer sintoma de falha do conector — "nao autenticado", "connector requires authentication", "token expirado", "nao consigo ler o notebook", "renova o token" — e quando alguem fizer uma pergunta respondivel com os documentos indexados.
---

# NotebookLM — servidor-gerente

> O endereco do servidor aparece escrito neste arquivo porque a skill nao le
> variavel de ambiente. Se o servidor mudar de host, troque aqui, no
> `plugin.json` e em `references/commands.md`, e reempacote o `.skill`. O valor
> tem que bater com o `PUBLIC_URL` do servidor e com o `redirect_uri` registrado
> no Google Cloud Console; se divergir, o sintoma e `Erro 400: redirect_uri_mismatch`.

Voce opera o NotebookLM atraves de um **servidor-gerente** no EasyPanel, que guarda os
tokens Google (cifrados com Fernet) no Postgres, identifica o usuario, aplica o nivel
de acesso, consulta o NotebookLM e grava tudo no `audit_log`.

Funcao dupla: **responder consultas com citacoes** e **manter os tokens funcionando**.

Leia `references/access-control.md` para a tabela de niveis e `references/commands.md`
para todos os comandos e exemplos.

---

## ⚠️ Modelo mental obrigatorio: sao DOIS tokens

Quase toda falha desta stack vem de confundir os dois. Leia antes de diagnosticar
qualquer coisa.

| | **Token 1 — Identidade** | **Token 2 — Scrap token** |
|---|---|---|
| O que e | OAuth Google (ou Bearer do Postgres) | `storage_state.json` — cookies de sessao do Google |
| Responde | *quem* esta chamando | acesso *real* ao NotebookLM |
| Onde vive | token OAuth do connector / coluna `api_token` | Postgres, cifrado com Fernet |
| Como nasce | vincular o connector no Claude.ai | `notebooklm login` no Chromium → `connect.py` |
| Quem resolve | `_current_email()` em `server/mcp_server.py` | `auth.get_client_for()` em `server/auth.py` |

**A ordem importa e nao tem atalho:** o servidor resolve a identidade **primeiro**.
Sem token 1, a chamada nem chega ao token 2.

> 🚨 **Corolario que engana todo mundo:** `renovar_token` e `verificar_token` existem
> para consertar o **token 2**, mas estao **atras do portao do token 1**. Se a
> identidade estiver quebrada, eles falham sem nunca tocar no Google. **Nao use
> `renovar_token` para diagnosticar "nao autenticado"** — ele nao pode, por construcao.

**O elo entre os dois e o email.** O email vindo do OAuth e a chave de busca do
storage_state (`db.get_storage_state(email)`). Se o usuario vincular o connector com
`fulano@gmail.com` mas o `connect.py` tiver subido o token sob `fulano@empresa.com`,
o OAuth passa e a busca estoura. **Tem que ser o mesmo email nos dois lados.**

---

## 🔧 Triagem — do erro para a causa

Sempre classifique o erro **antes** de sugerir acao. A mensagem diz qual camada caiu.

| Mensagem observada | Camada | Causa | Acao |
|---|---|---|---|
| `This connector requires authentication` | Token 1 | Connector nunca foi vinculado, ou o OAuth expirou | Settings → Connectors → Vincular → Continuar com Google |
| `Erro 400: redirect_uri_mismatch` na tela do Google | Token 1 | `/auth/callback` do host atual nao esta registrado no Google Cloud Console | Registrar o URI exato — ver "Verificar o deploy", item 2 |
| `{"erro":"Nao autenticado"}` (dict no corpo) | Token 1 | Servidor subiu **sem** auth provider — a chamada passou o portao e morreu na tool | `GOOGLE_OAUTH_CLIENT_ID/SECRET` vazios. Ver "Verificar o deploy" |
| `status: expired` / `Authentication expired or invalid` / `Redirected to accounts.google.com` | Token 2 | Cookies do Google rotacionaram e venceram | `notebooklm login` + re-rodar `connect.py` |
| `ValueError` em `get_storage_state` / "sem token" | Token 2 | Email autenticado nao tem storage_state no Postgres | Rodar `connect.py` **com o mesmo email do OAuth** |
| 401 na REST | Token 1 | `api_token` invalido ou usuario inativo | Admin reemite via `POST /api/admin/users` |
| 403 na REST | Nivel | Nivel insuficiente, ou onboarding token ja usado/expirado | Ver `references/access-control.md` |
| Notebook nao aparece na lista | Area | Classificacao **fail-closed**: notebook sem area fica invisivel p/ juridico/financeiro | `scripts/classifica_notebooks.py` |

**Distincao critica das duas primeiras linhas:** um *desafio de autenticacao* do
protocolo MCP significa que o servidor esta barrando na porta — comportamento
**correto**. Um *dict* `{"erro":"Nao autenticado"}` significa que a chamada entrou
sem identidade e falhou la dentro — o servidor esta **sem auth provider**. Sao
diagnosticos opostos com nomes parecidos.

---

## Tres caminhos de acesso

Se um estiver bloqueado, tente o proximo antes de declarar impossivel.

### 1. Conector MCP (preferencial)
Ferramentas nativas no Claude: `quem_sou_eu`, `listar_notebooks`, `perguntar`,
`listar_fontes`, `verificar_token`, `renovar_token`, `criar_notebook`, `adicionar_fonte`.
Identificacao por login Google, sem digitar email.

- `quem_sou_eu` — email, nivel e se ha token NotebookLM ativo
- `listar_notebooks` — notebooks visiveis (filtrados por area)
- `perguntar(notebook_id, pergunta)` — resposta + citacoes
- `listar_fontes(notebook_id)` — fontes indexadas
- `verificar_token` / `renovar_token` — testam de verdade, via rede, e persistem cookies rotacionados
- `criar_notebook(titulo)` — admin
- `adicionar_fonte(notebook_id, url | drive_file_id+titulo)` — gestor ou admin

**Adicionar o conector (uma vez):** Settings → Connectors → Add custom connector →
`https://connectors-notebooklm.tpgavy.easypanel.host/mcp` → Vincular →
Continuar com Google.

> O Claude.ai web exige OAuth em custom connectors (nao aceita token simples na UI).
> Por isso o OAuth serve **so para identificar** — nao e o token do NotebookLM.

### 2. CLI local (contorna o servidor inteiro)
O pacote `notebooklm` instalado na maquina usa o storage_state **local**
(`~/.notebooklm/profiles/<perfil>/storage_state.json`) e fala direto com o Google —
sem servidor, sem OAuth, sem Postgres. **E o caminho mais curto quando o connector
esta quebrado**, e o melhor jeito de provar se o problema e token 1 ou token 2.

```bash
notebooklm --profile <perfil> list          # lista notebooks
notebooklm --profile <perfil> doctor        # status do perfil e da auth
notebooklm --profile <perfil> login         # re-login (abre o Chromium)
notebooklm --profile <perfil> ask "..."     # pergunta no notebook ativo
```

> Em ambientes com sandbox de rede, `curl` e o CLI retornam codigo `000` / exit 43.
> Isso e a sandbox, **nao** o servidor fora do ar — confirme com um GET no `/health`
> por uma ferramenta de fetch antes de concluir que caiu.

### 3. REST (n8n, automacoes e diagnostico)
`GET /api/auth/check` chama exatamente a mesma `auth.check_auth()` do `renovar_token`,
mas autentica por **Bearer do Postgres** — ou seja, **funciona mesmo sem OAuth**. E a
forma de renovar o token 2 quando o connector esta inacessivel.

```bash
curl -s -H "Authorization: Bearer <api_token>" \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/auth/check
```

---

## Formato de resposta — consulta com citacoes

```
[CONSULTA NotebookLM]
Notebook: [nome]
Usuario: [email] ([nivel])

RESPOSTA
[resposta do NotebookLM]

FONTES CITADAS
[citacoes]

AVISO: baseado nos documentos indexados. Consulte um advogado para decisoes definitivas.
```

---

## Ciclo de vida do token 2

Os cookies do Google rotacionam e expiram — expiracao e o estado **normal**, nao
excecao. O servidor ja re-persiste cookies renovados no Postgres ao fim de cada
chamada (`server/auth.py`), entao **uso frequente mantem o token vivo**; o que mata
e ficar semanas sem chamar.

**Renovar (maquina local do usuario):**
```bash
cd <repo>/client
set NOTEBOOKLM_ONBOARDING_TOKEN=<token de uso unico — peca ao admin>
python connect.py --email <email> --nome "<Nome>"
```

**Onboarding de novo membro (2 passos):**
```bash
# 1) admin emite o onboarding token de uso unico, ligado ao email
curl -X POST -H "Authorization: Bearer <token_admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@escritorio.com","ttl_horas":48}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/admin/onboarding-token

# 2) o membro roda o connect.py (entra PENDENTE) e o admin ativa:
curl -X POST -H "Authorization: Bearer <token_admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@escritorio.com","nivel":"juridico","ativo":true}' \
  https://connectors-notebooklm.tpgavy.easypanel.host/api/admin/users
```

> A chave Fernet **nunca** vai para a maquina do usuario. `server/db/register.py`,
> `check.py` e `login.py` sao **break-glass de admin**, nao renovacao de usuario.
> O nivel nao e escolhido pelo proprio usuario — auto-atribuir seria escalonamento
> de privilegio.

> Recomendado: cron de 15–20 min com `notebooklm auth refresh --quiet` na maquina
> local para manter os tokens quentes.

---

## Verificar o deploy

```
GET /health                                   -> {"status":"ok"}
GET /.well-known/oauth-authorization-server   -> issuer, authorize, token, register
```

Se o segundo **nao existir**, o servidor subiu **sem auth provider** e todas as tools
vao devolver `{"erro":"Nao autenticado"}`.

**Tres pontos de configuracao que precisam conferir, em ordem de frequencia:**

1. **`GOOGLE_OAUTH_CLIENT_ID` ou `GOOGLE_OAUTH_CLIENT_SECRET` vazios.** O
   `auth_provider` fica `None`, o `FastMCP` sobe sem auth e **nao ha erro no log**.
   Sintoma exato: o dict `{"erro":"Nao autenticado"}`.
2. **`redirect_uri` nao registrado no Google Cloud Console.** Sintoma: `Erro 400:
   redirect_uri_mismatch` na tela do Google, depois de clicar em Vincular. O
   `GoogleProvider` monta o callback como `base_url.rstrip("/") + redirect_path`, com
   `redirect_path` default `/auth/callback`. Para este servidor, o valor exato e:

   ```
   https://connectors-notebooklm.tpgavy.easypanel.host/auth/callback
   ```

   Tem que estar em **URIs de redirecionamento autorizados** do cliente OAuth 2.0
   correspondente ao `GOOGLE_OAUTH_CLIENT_ID`. Trocar de host (ex.: aposentar o
   `tpgavy`) **quebra o OAuth** ate o URI novo ser registrado la.

   > Barra final no `PUBLIC_URL` e **inofensiva** — o FastMCP faz `rstrip("/")` antes
   > de concatenar (`oauth_proxy/proxy.py`, `oauth_proxy/consent.py`). O `issuer` do
   > metadata aparecer com barra tambem nao e sintoma de nada. Nao perca tempo ai.
3. **`NOTEBOOKLM_ALLOWED_DOMAINS` / `ALLOWED_EMAILS` preenchidos.** Email fora da lista
   e recusado **depois** do OAuth completar com sucesso — parece erro de token, mas o
   log diz "email fora da allowlist". Vazio = sem restricao de front-door.

---

## Controle de acesso

> Tabela completa em `references/access-control.md`. O servidor aplica automaticamente.

- **admin** → tudo
- **gestor** → consulta tudo, sem criar/deletar
- **juridico** → consulta (notebooks juridicos/processos)
- **financeiro** → consulta (notebooks financeiros) — nivel **paralelo**, nao inferior

Controle por nivel de comando + por area de notebook (tabela `notebooklm.notebooks`),
**fail-closed**: notebook sem classificacao fica invisivel para juridico/financeiro
(admin/gestor veem tudo). Classificacao via `scripts/classifica_notebooks.py`
(gera CSV → revisao humana → `POST /api/admin/notebooks-classificacao`).

**Nunca revelar:** storage_state, `NOTEBOOKLM_ENCRYPTION_KEY`, `DATABASE_URL`,
tokens/cookies, `api_token` de terceiros, ou dados de outros usuarios para quem nao
e admin. **Nunca pedir ao usuario que cole um Bearer de admin no chat** — ele da
acesso total ao conector; prefira instruir o usuario a rodar o comando e reportar
so o `status`.

---

## API REST

Base: `https://connectors-notebooklm.tpgavy.easypanel.host/api`
Auth: `Authorization: Bearer <token-do-usuario>` (o nivel vem do token, nunca de header).
Excecao: `/token/upload` usa `X-Onboarding-Token` (uso unico, por-usuario) — e o bootstrap.

| Metodo | Rota | Nivel |
|---|---|---|
| GET | `/api/health` | publico |
| GET | `/api/auth/check` | ativo |
| GET | `/api/notebooks` | ativo (filtra area) |
| POST | `/api/notebooks` | admin |
| GET | `/api/notebooks/{id}/sources` | ativo |
| POST | `/api/notebooks/{id}/sources` | gestor |
| POST | `/api/notebooks/{id}/ask` | ativo |
| GET | `/api/team` | admin |
| POST | `/api/admin/users` | admin (ativa + emite token) |
| POST | `/api/admin/onboarding-token` | admin |
| POST | `/api/token/upload` | onboarding token (cadastro pendente) |

---

## Infraestrutura

- **Servidor:** `https://connectors-notebooklm.tpgavy.easypanel.host` (MCP em `/mcp`, REST em `/api`) — preenchido no
  empacotamento do `.skill`; o valor tem que ser o mesmo do `PUBLIC_URL` do servidor
- **Postgres:** tabelas `users`, `tokens`, `notebooks`, `audit_log` (append-only por trigger)
- **Hosts aposentados:** `memory-be-main.tpgavy.easypanel.host` — fora do ar,
  responde 404 em HTML. Se aparecer em alguma config antiga, e referencia velha:
  o endereco em uso e o do servidor listado acima.
