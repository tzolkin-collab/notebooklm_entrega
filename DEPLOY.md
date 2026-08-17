# Deploy

Runbook para subir o connector numa instância EasyPanel.

A ordem importa. Os passos 2 e 3 invertidos derrubam o login de toda a equipe.

---

## 0. Ponto de partida

**A infraestrutura já existe.** A organização tem servidor próprio (EasyPanel) —
não é preciso provisionar hospedagem. O que este runbook cobre é publicar esta
versão nele e criar o material de credencial.

A distinção importa: infra herdada é aceitável e é o caso aqui; **credencial**
herdada não é.

| Recurso | Estado | O que fazer |
|---|---|---|
| Runtime | **existe** | criar/apontar o serviço do app no EasyPanel da organização |
| Postgres | **verificar** | ver a decisão abaixo |
| Cliente OAuth | criar | no Google Cloud da organização — passo 2 |
| Chave Fernet | **gerar nova** | passo 3 |

A chave Fernet é inegociável: a que existia passou por mãos de outra empresa
durante o desenvolvimento. Chave que atravessa organizações deixa de proteger o
que cifra — gere uma nova mesmo que encontre a antiga configurada no ambiente.

O que precisa ser decidido antes do passo 1:

- **Reaproveitar o Postgres existente ou criar um novo.** Se houver um banco do
  ambiente anterior, ele carrega o `audit_log` histórico — que é registro de
  consulta sob sigilo profissional e provavelmente deve ser preservado, não
  descartado por conveniência. Mas os `tokens` guardados nele estão cifrados com
  a **chave antiga**: com chave Fernet nova eles se tornam ilegíveis, e a equipe
  refaz o login de qualquer forma (passo 7). Decida com o cliente.
- Host definitivo e `PUBLIC_URL` correspondente.

---

## 1. Postgres

Criar o Postgres **dentro do mesmo projeto EasyPanel do app** e conectar pelo
nome de serviço interno — nunca pelo domínio público com porta mapeada.

```bash
# Certo: rede interna do Docker, o tráfego não sai do host
export DATABASE_URL='postgres://user:senha@postgres:5432/notebooklm?sslmode=disable'

# Errado: sai do host, atravessa a internet e volta
# export DATABASE_URL='postgres://user:senha@easypanel.<dominio>.com:9000/notebooklm?sslmode=disable'
```

> **Por que não `sslmode=require`.** O Postgres do EasyPanel sobe sem TLS
> configurado — sondando o handshake, o servidor responde `N` ao `SSLRequest`.
> Pedir `require` não protege nada: só impede a conexão. Em rede interna isolada
> o `disable` é aceitável, e é a ressalva que o próprio `.env.example` faz. O que
> não fecha é `disable` **e** host público ao mesmo tempo — combinação fácil de
> chegar por acidente, quando se resolve um erro de conexão trocando o `sslmode`
> sem trocar o host. É por isso que esta seção existe.

Aplicar o schema. `schema.sql` é idempotente (`IF NOT EXISTS`), então rodar duas
vezes é seguro.

```bash
python server/db/apply_schema.py
```

Saída esperada: `Schema aplicado com sucesso.` seguido das tabelas
`access_log`, `audit_log`, `notebook_owners`, `notebook_shares`, `notebooks`,
`onboarding_tokens`, `tokens`, `users`.

> `audit_log` e `access_log` têm trigger append-only. UPDATE/DELETE são
> rejeitados no banco, não só no código.

---

## 2. OAuth — cliente próprio

O cliente OAuth precisa viver no Google Cloud da organização. Reaproveitar o de
outro projeto funcionaria tecnicamente, mas deixaria a equipe autenticando
através de um projeto Google que ela não controla.

Criar um cliente OAuth 2.0 **no Google Cloud da organização**:

1. Tipo: *Aplicativo da Web*
2. URI de redirecionamento autorizado, exatamente assim:
   ```
   https://<host>/auth/callback
   ```
3. Consent screen no domínio dele (`exemplo.com` /
   `outro-dominio.com`) — interno, se o Workspace permitir
4. Client id e secret novos vão para as variáveis do passo 3

> O `redirect_uri` é montado como `PUBLIC_URL + "/auth/callback"`. Se não bater
> caractere por caractere com o registrado, o sintoma é `Erro 400:
> redirect_uri_mismatch` na tela do Google.

**Consequência:** client id novo significa consent novo. Cada pessoa passa pela
tela de autorização uma vez — o que já ia acontecer de qualquer forma, já que os
tokens não são migrados (passo 6).

---

## 3. Variáveis de ambiente no EasyPanel

Gere uma chave Fernet **nova** para este deploy. Não reaproveite a de outro
servidor — se a chave viaja, os dados cifrados com ela não estão protegidos de
quem tem a cópia.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Variáveis obrigatórias (o servidor **não sobe** sem estas três):

| Variável | Observação |
|---|---|
| `NOTEBOOKLM_ENCRYPTION_KEY` | Fernet nova, vive só no servidor |
| `DATABASE_URL` | `sslmode=require` fora de rede interna isolada |
| `PUBLIC_URL` | URL pública deste deploy, sem barra final |

Recomendadas:

| Variável | Valor |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` | sem eles o `/mcp` sobe sem autenticação |
| `NOTEBOOKLM_ALLOWED_DOMAINS` | `exemplo.com,outro-dominio.com` |
| `FORWARDED_ALLOW_IPS` | IP/CIDR do proxy do EasyPanel — **nunca `*`** |
| `NOTEBOOKLM_AUDIT_FAIL_CLOSED` | `true` em produção jurídica |

Referência completa comentada: `server/.env.example`.

---

## 4. Build e subida

O `.dockerignore` mantém `.env`, `.git`, `client/` e `scripts/` fora da imagem.
Confirme antes de publicar em qualquer registry:

```bash
docker build --tag notebooklm:deploy .
docker run --rm notebooklm:deploy sh -c 'ls -la /app/.env 2>&1; ls -d /app/.git 2>&1'
```

Esperado: `No such file or directory` nas duas. Se qualquer uma aparecer, **não
publique a imagem** — ela carrega segredo do ambiente de quem buildou.

---

## 5. Validação

```bash
curl -s https://<host>/health          # {"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' https://<host>/mcp   # 401
curl -s https://<host>/.well-known/oauth-authorization-server | head -c 200
```

O `issuer` no metadata tem que ser o host da organização. Se aparecer outro, o
`PUBLIC_URL` está errado — corrija antes de liberar para a equipe.

---

## 6. Primeiro admin

O cadastro self-service cria usuário **pendente** (`ativo=false`, nível
`juridico`). Ninguém se auto-promove. O primeiro admin é criado direto no banco:

```bash
export DATABASE_URL='...'
python server/db/register.py    # confira os argumentos no próprio script
```

Depois disso, ativações e níveis passam a ser feitos por `POST /api/admin/users`.

---

## 7. Onboarding da equipe

Para cada pessoa:

1. Admin emite token de uso único: `POST /api/admin/onboarding-token`
2. A pessoa roda, na máquina dela:

```bash
set NOTEBOOKLM_SERVER_URL=https://<host>
set NOTEBOOKLM_ONBOARDING_TOKEN=<token-recebido>
python client/connect.py
```

3. Admin ativa e define o nível

> `connect.py` não tem mais URL default — ele recusa rodar sem
> `NOTEBOOKLM_SERVER_URL`. É proposital: o script envia os cookies da sessão
> Google da pessoa, e um default embutido mandaria a credencial para o servidor
> errado sem ninguém perceber.

---

## 8. Plugin do Claude

`client/plugin/plugin.json` traz `<PUBLIC_URL>` como placeholder em três campos —
esse arquivo **não lê variável de ambiente**. Substitua pelo host da organização
antes de reempacotar o `.skill`, e confira que bate com o `PUBLIC_URL` do servidor
e com o `redirect_uri` registrado no Google.

---

## 9. Classificação dos notebooks

Sem classificação na tabela `notebooks`, o filtro por área é **fail-closed**:
`juridico` e `financeiro` enxergam lista vazia (só `admin` e `gestor` veem tudo).
É inconveniência proposital, no lugar de vazamento — mas significa que a equipe
fica sem acesso até a classificação rodar.

```bash
set NOTEBOOKLM_SERVER_URL=https://<host>
python scripts/classifica_notebooks.py
```

---

## Pendências conhecidas

- Rate limit é in-memory nos dois lados (MCP e REST). Correto para 1 worker
  uvicorn, que é a configuração atual do `Dockerfile`. Escalar horizontalmente
  exige backend compartilhado antes.
- `_db_params()` em `db.py` remonta o dict de conexão à mão e descarta todo
  parâmetro de query exceto `sslmode` — `connect_timeout`, `application_name` e
  afins são silenciosamente ignorados.

---
