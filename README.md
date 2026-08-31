# NotebookLM Connector

Assistente jurídico dentro do Claude: a equipe consulta o acervo do
NotebookLM (~277 notebooks) com citações, através de um conector MCP com login
Google, com nível de acesso por função e auditoria completa.

---

## Como funciona

O servidor guarda os tokens Google de cada pessoa (cifrados com Fernet) no
Postgres, identifica quem está chamando, aplica o nível de acesso, consulta o
NotebookLM e registra tudo no `audit_log`. Duas interfaces, cada uma com sua
autenticação:

```
Claude  ──(OAuth Google)──────────────→ /mcp ─┐
                                              ├─→ servidor ─→ Postgres (token cifrado) ─→ NotebookLM
n8n     ──(Authorization: Bearer …)───→ /api ─┘        └─→ nível de acesso → audit_log
```

- **`/mcp`** — conector MCP do Claude, via **OAuth Google**. O email vem do token
  assinado, não de um header. É o caminho para pessoas.
- **`/api`** — REST para automações. **Token Bearer por usuário**: a identidade e
  o nível saem do token no banco.

**Níveis:** `admin` · `gestor` · `juridico` · `financeiro`. Jurídico e financeiro
são paralelos, não hierárquicos — cada um vê os notebooks da sua área.

**Fail-closed:** notebook sem classificação de área é invisível para `juridico` e
`financeiro` (`admin` e `gestor` veem tudo). Inconveniência no lugar de
vazamento — mas significa que a equipe fica sem acesso até a classificação rodar.

---

## Rodar localmente

Requer Python 3.13 (3.11+ funciona para os testes).

```bash
git clone <repositorio>
cd notebooklm-connector

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -r server/requirements-dev.txt   # já puxa o requirements.txt
```

### Testes

```bash
pytest
```

44 testes, ~2s. Cobrem autenticação dual (OAuth + Bearer) e o controle de acesso
por área. O `pytest.ini` cuida de `pythonpath` e `asyncio_mode` — não passe flags.

Não é preciso banco nem rede: um fixture bloqueia conexão real com o Postgres e
falha na hora se algum mock estiver no alvo errado.

> `db.py` ainda não tem cobertura — ver
> `HANDOFF.md`, seção final.

### Subir o servidor na sua máquina

```bash
cp server/.env.example server/.env
# preencha: NOTEBOOKLM_ENCRYPTION_KEY, DATABASE_URL, PUBLIC_URL

cd server
python db/apply_schema.py        # cria o schema notebooklm.*
uvicorn main:app --reload --port 8000
```

As três variáveis acima são **obrigatórias** — o servidor não sobe sem elas, de
propósito. `PUBLIC_URL` define o `redirect_uri` do OAuth; um default errado faria
o login passar por outro servidor sem ninguém perceber.

Gere a chave Fernet com:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## Deploy do servidor

Runbook completo em **[DEPLOY.md](DEPLOY.md)** — a ordem dos passos importa, e
inverter os primeiros derruba o login de toda a equipe.

Resumo: EasyPanel apontando para este repositório, build por Dockerfile, porta
interna 80. Postgres **no mesmo projeto**, acessado por nome de serviço interno.
Cliente OAuth próprio no Google Cloud, com o `redirect_uri` registrado antes da
virada.

Antes de publicar a imagem em qualquer registry:

```bash
docker build --tag notebooklm:deploy .
docker run --rm notebooklm:deploy sh -c 'whoami; ls -la /app/.env 2>&1; ls -d /app/.git 2>&1'
```

Esperado: `appuser` e `No such file or directory` nas duas. Se `.env` ou `.git`
aparecerem, a imagem carrega a chave Fernet e a senha do banco — não publique.

---

## Usar

> Guia completo de conceder, revogar e manter acessos: **[ACESSOS.md](ACESSOS.md)**.
>
> Versão sem termos técnicos, endereçada ao Doutor:
> **[GUIA-DO-DOUTOR.md](GUIA-DO-DOUTOR.md)**.
>
> Assumindo o projeto agora? Comece por
> **[GUIA-DA-CONSULTORIA.md](GUIA-DA-CONSULTORIA.md)**.

### 1. Onboarding (cada pessoa, uma vez)

O admin emite um token de uso único ligado ao email:

```bash
curl -X POST -H "Authorization: Bearer <token-admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@exemplo.com","ttl_horas":48}' \
  <PUBLIC_URL>/api/admin/onboarding-token
```

A pessoa roda, na máquina dela:

```bash
cd client
set NOTEBOOKLM_SERVER_URL=<PUBLIC_URL>
set NOTEBOOKLM_ONBOARDING_TOKEN=<token recebido>
python setup.py
```

`setup.py` instala as dependências e o Chromium, e roda `connect.py`: login
Google, e o token vai por HTTPS para o servidor, que cifra e cria o cadastro
**pendente**.

O admin então ativa e define o nível:

```bash
curl -X POST -H "Authorization: Bearer <token-admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@exemplo.com","nivel":"juridico","ativo":true}' \
  <PUBLIC_URL>/api/admin/users
```

> O cadastro entra inativo de propósito: ninguém se auto-promove pelo upload.
> Nível e ativação são decisão de um admin.

### 2. Conector no Claude

Settings → Connectors → Add custom connector → `<PUBLIC_URL>/mcp` → Vincular →
Continuar com Google.

As 13 ferramentas registradas em `mcp_server.py`:

| Identidade e sessão | Acervo | Compartilhamento |
|---|---|---|
| `quem_sou_eu` | `listar_notebooks` | `listar_compartilhados` |
| `verificar_token` | `perguntar` | `compartilhar_notebook` |
| `renovar_token` | `listar_fontes` | `status_compartilhamento` |
| `criar_vinculo_bot` | `criar_notebook` | `sincronizar_compartilhamentos` |
| | `adicionar_fonte` | |

Do escopo original **não** foram construídas: `gerar_relatorio`, `gerar_podcast`,
`baixar_artefato` (fase 3) e `historico` (fase 4). Verificado por busca no
`server/`: zero ocorrências. A fase 3 estava descrita no `ESCOPO.md` como a
entrega de maior valor percebido pelo cliente — quem assumir precisa saber que
ela não existe.

### 3. REST (n8n e automações)

Base `/api`. Tudo exige `Authorization: Bearer <token-do-usuário>`, exceto
`/health` (público) e `/token/upload` (usa `X-Onboarding-Token`).

| Método | Rota | Limite | Nível |
|---|---|---|---|
| `GET` | `/health` | — | público |
| `GET` | `/auth/check` | 10/min | ativo |
| `GET` | `/notebooks` | 30/min | ativo (filtra por área) |
| `POST` | `/notebooks` | 10/min | admin |
| `GET` | `/notebooks/{id}/sources` | 30/min | ativo |
| `POST` | `/notebooks/{id}/sources` | 10/min | gestor |
| `POST` | `/notebooks/{id}/ask` | 20/min | ativo |
| `GET` | `/team` | 10/min | admin |
| `POST` | `/admin/bootstrap` | 5/min | `X-Bootstrap-Key` (segredo do servidor) |
| `POST` | `/admin/users` | 10/min | admin |
| `POST` | `/admin/onboarding-token` | 10/min | admin |
| `POST` | `/admin/notebooks-classificacao` | 10/min | admin |
| `POST` | `/token/upload` | 10/min | — (cadastro pendente) |
| `POST` | `/token/link` | 5/min | ativo (gera vínculo p/ bot) |
| `POST` | `/bot/token` | 10/min | `X-Bot-Key` (segredo do bot) |

**401** = token inválido ou inativo. **403** = nível insuficiente, ou token de
onboarding inválido/expirado/já usado.

```bash
curl -X POST -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"question": "Quais precedentes sobre dano moral digital?"}' \
  <PUBLIC_URL>/api/notebooks/<id>/ask
```

### 4. Vínculo via bot (WhatsApp e afins)

Alternativa ao onboarding manual do item 1, para quem já tem cadastro ativo:
um bot de chat pode capturar a sessão Google da pessoa e entregá-la ao
servidor sem que ela precise rodar `connect.py` na própria máquina.

1. A pessoa (já ativa) chama `criar_vinculo_bot` no MCP, ou
   `POST /api/token/link` com o próprio Bearer — recebe um `link_token` de
   uso único, válido por 10 minutos.
2. Ela entrega esse código ao bot confiável.
3. O backend do bot captura a sessão e chama
   `POST <PUBLIC_URL>/api/bot/token` com `X-Bot-Key`, o `link_token` e a
   conta Google identificada no login.

Protocolo completo, erros e limites: **[docs/BOT-TOKEN.md](docs/BOT-TOKEN.md)**.
Adaptador de referência: `scripts/bot/send_token.py`.

### 5. Bootstrap do primeiro admin

Não há como emitir token de admin sem um admin. Caminho normal, por HTTPS,
sem acesso direto ao banco:

```bash
curl -X POST -H "Content-Type: application/json" -H "X-Bootstrap-Key: <NOTEBOOKLM_BOOTSTRAP_KEY>" \
  -d '{"email":"admin@exemplo.com","nome":"Admin"}' \
  <PUBLIC_URL>/api/admin/bootstrap
```

`NOTEBOOKLM_BOOTSTRAP_KEY` é um segredo à parte do `api_token`, definido só no
ambiente do servidor (ver `server/.env.example`) — quem a possui já teria o
mesmo alcance com acesso direto ao Postgres. Idempotente: pode ser chamado de
novo para promover outro email a admin.

Break-glass (sem servidor no ar, acesso direto ao banco):

```bash
set DATABASE_URL=postgres://...
python server/db/gen_token.py --email admin@exemplo.com
```

### 6. Classificar os notebooks

Sem isso o fail-closed deixa `juridico` e `financeiro` sem ver nada.

```bash
set NOTEBOOKLM_SERVER_URL=<PUBLIC_URL>
python scripts/classifica_notebooks.py --gerar --profile default   # gera CSV
# revisar a coluna 'area' no CSV
set NOTEBOOKLM_ADMIN_TOKEN=<token-admin>
python scripts/classifica_notebooks.py --enviar
```

---

## Estrutura

```
├── server/                   ← deploy (guarda a chave Fernet e o acesso ao banco)
│   ├── main.py               ← entry point: monta /mcp na raiz e /api em /api
│   ├── mcp_server.py         ← conector MCP, OAuth Google + Bearer
│   ├── api.py                ← REST
│   ├── rpc.py                ← chamadas ao NotebookLM + filtro por área
│   ├── db.py · auth.py · config.py
│   ├── tests/                ← pytest (não entra na imagem)
│   └── db/
│       ├── schema.sql        ← audit_log, access_log e bot_links; aplicado
│       │                        sozinho a cada start do container
│       ├── apply_schema.py
│       ├── gen_token.py      ← bootstrap do primeiro admin, break-glass
│       └── register.py · check.py · login.py   ← break-glass de admin
├── client/                   ← máquina do usuário (nunca recebe a chave Fernet)
│   ├── connect.py            ← onboarding: login Google + upload do token
│   ├── setup.py
│   └── plugin/               ← skill do Claude
├── scripts/                  ← classificação dos notebooks por área
│   └── bot/                  ← adaptador de vínculo por bot (ver item 4 acima)
└── DEPLOY.md                 ← runbook do servidor
```

**Fronteira:** a chave Fernet e a `DATABASE_URL` vivem só no servidor. As
ferramentas que precisam delas ficam em `server/db/` e são break-glass de admin —
nunca rodam em máquina de usuário. Usuários usam apenas `client/connect.py`.

---

## Segurança

O que está implementado:

- Tokens Google cifrados com **Fernet** no Postgres; a chave só no servidor
- Token decifrado em disco apenas em arquivo temporário **0600**, apagado ao fim
- Bearer **por usuário** na REST — sem email spoofável nem chave única que vira admin
- `/token/upload` autorizado por token de **uso único, ligado ao email, com
  expiração**; não concede privilégio (cadastro entra inativo)
- OAuth do MCP recusa email não-verificado; allowlist opcional por domínio
- Rate limit por usuário no MCP, por IP na REST
- `audit_log` e `access_log` **append-only por trigger no banco** — não só no código
- Opção **fail-closed** de auditoria (`NOTEBOOKLM_AUDIT_FAIL_CLOSED`): não responde
  sem gravar
- Container roda como usuário **sem privilégio** (uid 1000)
- `.dockerignore` mantém `.env`, `.git` e tokens fora da imagem

Limitações conhecidas, para não haver surpresa:

- **Rate limit conta em memória, por processo.** Só está correto porque o
  `Dockerfile` sobe um worker. Adicionar `--workers N` multiplica o limite
  efetivo por N, sem erro e sem log.
- **TLS no Postgres depende do servidor.** O código exige `sslmode=require`
  quando não especificado, mas instâncias EasyPanel sobem sem TLS configurado —
  aí `require` impede a conexão em vez de proteger. Em rede interna isolada,
  `disable` é aceitável; `disable` **com host público** não é.
- **O conteúdo das consultas e respostas fica no `audit_log`.** Cifrado, mas com
  a chave do servidor: quem opera o servidor lê tudo. Isso é dado sob sigilo
  profissional — o acesso ao banco e ao ambiente precisa ser tratado como tal.
- `db.py` sem cobertura de teste (ver `HANDOFF.md`).

**Regra de segredos:** só em variável de ambiente. Nunca em README, código, docs
ou no bundle `.skill`. Se alguém novo ganhar acesso ao repositório ou ao servidor,
rotacione a chave Fernet e a senha do Postgres antes, e refaça o `connect.py` de
todo mundo.

