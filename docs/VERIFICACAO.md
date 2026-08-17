# Verificação contra instância real

Tudo abaixo foi observado num deploy em funcionamento, não deduzido do código.
A distinção importa: duas das descobertas contradizem o que a documentação
afirmava, e nenhuma das duas apareceria lendo o código.

Data: 12/08/2026.

---

## Respostas de recusa, endpoint por endpoint

Sem nenhuma credencial:

| Método | Rota | HTTP |
|---|---|---|
| `GET` | `/api/health` | `200` |
| `GET` | `/api/auth/check` | `401` |
| `GET` | `/api/notebooks` | `401` |
| `GET` | `/api/team` | `401` |
| `POST` | `/api/admin/users` | `401` |
| `POST` | `/api/admin/onboarding-token` | `401` |
| `POST` | `/api/token/upload` | `422` |

Corpos observados:

```
sem token          → {"detail":"Not authenticated"}
Bearer inválido    → {"detail":"Token de usuario invalido ou inativo"}
```

### O `/token/upload` valida o payload antes do token

Ele é o único que não devolve `401`, e a razão é a ordem de validação: o FastAPI
checa o formato do corpo (Pydantic) antes de o código conferir o token de
onboarding.

| Situação | HTTP | Mensagem |
|---|---|---|
| `storage_state` vazio ou malformado | `422` | `storage_state sem cookies Google validos` |
| payload OK, sem header de token | `403` | `Token de onboarding ausente (peça um ao admin)` |
| payload OK, token inválido | `403` | `Token de onboarding inválido, expirado, já usado ou não corresponde ao email` |

Consequência prática para quem der suporte: **o `422` significa que o login no
Chromium não produziu cookies válidos** — quase sempre o login foi fechado antes
de terminar. Não é problema de token, e mandar a pessoa pedir outro token não
resolve.

E a mensagem de `403` junta **quatro** causas diferentes numa frase só. Quem
recebe não consegue distinguir "preciso de um token novo" de "usei o email
errado". Vale separar, se algum dia alguém mexer nesse endpoint.

---

## O rate limit não protege o que parece proteger

O `README` lista limites por rota (10/min, 20/min, 30/min). Testando:

**`/api/auth/check`** — limite documentado de 10/min. Treze requisições sem
credencial:

```
401 401 401 401 401 401 401 401 401 401 401 401 401
```

Nenhum `429`. O limite **nunca disparou**.

**`/api/token/upload`** — também 10/min. Treze requisições:

```
403 403 403 403 403 403 403 403 403 403 429 429 429
```

Disparou exatamente na décima primeira.

### Por que a diferença

O `slowapi` aplica o limite decorando a função da rota. Mas o FastAPI resolve as
dependências (`Depends`) **antes** de chamar a função. Nos endpoints em que a
autenticação é uma dependência, o `401` acontece antes de o contador existir.

O `/token/upload` confere o token **dentro** do corpo da função — por isso ali o
limite funciona.

Ou seja: **em todos os endpoints protegidos por `Depends`, uma chamada não
autenticada não é contada.** Um cliente sem credencial pode repetir
indefinidamente.

### Qual é o risco real

Não é adivinhar token: o `api_token` tem 32 bytes aleatórios, força bruta está
fora de questão.

O risco é carga. Cada tentativa faz um SHA-256 e uma consulta ao Postgres. Sem
limite, um cliente não autenticado sustenta essa carga contra o banco de graça.

### A correção óbvia não funciona

O caminho aparente era o `SlowAPIMiddleware`, que age antes da resolução de
dependências. **Não resolve** — e só descobri isso testando: o middleware rodava
e não limitava nada.

A razão está no `_should_exempt` do próprio slowapi:

```python
# there is a decorator for this route we let the decorator handle it
if name in limiter._route_limits:
    return True
```

Ele pula, deliberadamente, toda rota que tem `@limiter.limit()` — delegando ao
decorador. Ou seja: ignora exatamente as rotas quebradas.

### O que foi feito

Um middleware próprio, `TetoGlobalMiddleware`: janela deslizante por IP,
avaliada antes de qualquer rota. Os limites por rota do slowapi continuam
valendo depois da autenticação; este é o teto de abuso.

`/health` fica isento. O `HEALTHCHECK` do container bate nele a cada 30s, e
limitar o próprio healthcheck faria o container reiniciar sob carga —
transformando excesso de tráfego em queda de serviço.

Verificado com teto reduzido a 3/min:

```
sem credencial:  401 401 401 429 429 429      <- barra na 4ª
/health:         200 200 200 200 200 ...      <- isento
IP diferente:    401                          <- não é afetado pelo IP barrado
```

Coberto por `server/tests/test_rate_limit.py`, verificado por mutação: removendo
o `add_middleware`, 3 dos 4 testes falham.

### O balde é por IP — mas só se o proxy estiver declarado

Os logs do deploy mostram **`10.11.0.11`** como cliente de todas as requisições.
Esse é o proxy do EasyPanel, não o usuário. Com `FORWARDED_ALLOW_IPS=127.0.0.1`,
o uvicorn não confia no `X-Forwarded-For` vindo dele, e `get_remote_address()`
devolve o IP do proxy para todo mundo.

Consequência: **o rate limit vira um balde único compartilhado por toda a
organização.** Um usuário abusivo barra os outros.

A correção é de configuração, não de código — `FORWARDED_ALLOW_IPS` com o IP ou
a faixa do proxy (ex.: `10.11.0.0/16`). Não a apliquei porque depende da
topologia do ambiente de destino, e um valor errado aqui é pior que o problema:
confiar em `X-Forwarded-For` da origem errada deixa qualquer cliente forjar o
próprio IP e escapar do limite.

---

## O schema da API estava público

`/docs` e `/redoc` davam `404`, como o `README` afirmava. Mas:

```
GET /api/openapi.json → 200
```

O schema completo: onze rotas, parâmetros, esquemas de autenticação. E o `title`
do FastAPI, que naquele deploy nomeava a organização cliente.

Desligar `docs_url` e `redoc_url` **não desliga** o `openapi_url` — é um terceiro
parâmetro. Corrigido no código entregue:

```python
app = FastAPI(title=..., docs_url=None, redoc_url=None, openapi_url=None)
```

Depois de subir, confirmar que `/api/openapi.json` devolve `404`.

---

## Cabeçalhos de resposta

O único cabeçalho presente é `Server: uvicorn`. Não há `Strict-Transport-Security`,
`X-Content-Type-Options`, `X-Frame-Options` nem CSP.

Para uma API consumida por programa isso é pouco relevante — não há navegador
renderizando nada. O HSTS vale a pena se o proxy à frente não o adicionar; os
demais, não mudam nada aqui.

---

## O que continua sem verificação

Estes exigem credencial ou docker, e não foram executados:

- **Rate limit do MCP** (`_rate_ok`), que é código diferente do da REST
- **Expiração e renovação da sessão Google**

### Imutabilidade do log: verificada, com uma falha corrigida

Executado contra banco real em 12/08/2026:

```bash
python server/db/verifica_auditoria.py --com-truncate
```

**Primeira execução — 8 de 10:**

```
[PASSOU] audit_log: trigger presente
[PASSOU] audit_log: INSERT aceito
[PASSOU] audit_log: UPDATE recusado
[PASSOU] audit_log: DELETE recusado
[FALHOU] audit_log: TRUNCATE recusado — o banco ACEITOU a operacao
[FALHOU] access_log: TRUNCATE recusado — o banco ACEITOU a operacao
```

O trigger era `BEFORE UPDATE OR DELETE`. No Postgres, `TRUNCATE` é um evento de
gatilho **separado** — não estava coberto. Na prática:
`TRUNCATE TABLE notebooklm.audit_log` apagaria a trilha inteira sem reclamação.

Só apareceu porque o teste rodou. Lendo o schema, "append-only garantido por
trigger no banco" parecia completo.

**Correção aplicada** ao `schema.sql` — gatilho próprio para o evento, com
`FOR EACH STATEMENT`, porque `TRUNCATE` não tem linha a percorrer e o Postgres
recusa `FOR EACH ROW` na criação:

```sql
CREATE TRIGGER trg_audit_log_no_truncate
    BEFORE TRUNCATE ON notebooklm.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION notebooklm.audit_log_append_only();
```

**Segunda execução — 10 de 10.** As quatro operações destrutivas recusadas pelo
banco, nas duas tabelas.

A mensagem de erro também foi corrigida: a função é compartilhada pelas duas
tabelas e dizia sempre `notebooklm.audit_log`, mesmo quando a recusa vinha do
`access_log`. Agora usa `TG_TABLE_NAME`.

### O que o teste garante

Que `UPDATE`, `DELETE` e `TRUNCATE` são recusados **pelo banco**, não pelo
código — inclusive para o superusuário `postgres`, que foi com quem rodou. Se
fosse questão de permissão, o superusuário passaria.

Roda numa transação com savepoints e termina em `ROLLBACK`: nem a linha de teste
sobrevive. Confirmado depois — as duas tabelas seguiram com 0 linhas.

> Detalhe sem consequência: as sequências avançam mesmo com rollback (`id=1`
> virou `id=2` na segunda execução). Sequência não é transacional no Postgres.
> A tabela continua vazia.


---

## Fluxo de autorização, ponta a ponta

Executado contra a instância no ar em 12/08/2026, com um usuário de teste
descartável criado e removido no fim — a conta de desenvolvimento não foi tocada.

| Situação | Resultado |
|---|---|
| Bearer válido, nível `juridico`, em `/team` | `403` — "Seu nivel: juridico. Necessario: admin" |
| idem em `POST /notebooks` | `403` |
| promovido a `admin`, em `/team` | `200` com a lista |
| `admin` emitindo token de onboarding | `200`, devolve `onb_…` |
| desativado (`ativo=false`, `api_token=NULL`) | `401` — "Token de usuario invalido ou inativo" |
| **`GET /notebooks` sem sessão Google** | **`500 Internal Server Error`** |

Os cinco primeiros confirmam o modelo de níveis e a revogação. O último era
defeito.

### O `500` — corrigido

Usuário autenticado, ativo, com Bearer válido, mas sem `storage_state` no banco:
os seis endpoints que passam por `rpc.*` devolviam `500`. O `/auth/check`
tratava o mesmo caso e respondia direito, o que escondeu a diferença.

Não é estado exótico: é o de qualquer pessoa ativada antes de rodar o
`connect.py`, ou cuja sessão foi removida. E "Internal Server Error" não diz a
ninguém o que fazer.

A causa: o único `raise ValueError` do servidor está no `db.py`, três camadas
abaixo do endpoint, e não havia handler para ele — enquanto o `PermissionError`
do fail-closed tinha. Corrigido com um handler espelhando aquele:

```python
@app.exception_handler(ValueError)   # -> 409 + campo "acao"
```

`409` e não `401`/`403`: a credencial está certa e o nível também; o que falta é
um pré-requisito de estado. Tratar como falha de autenticação mandaria a pessoa
procurar o problema no lugar errado.

Coberto por `server/tests/test_api_erros.py`, e verificado por mutação —
trocando o handler por outro tipo de exceção, o teste falha.

### Ainda sem verificação

O round-trip real com o NotebookLM (listar e perguntar de verdade) exige uma
sessão Google válida, que só nasce do `connect.py` com login humano no Chromium.
O usuário de teste não tinha — por isso o `500` apareceu, o que acabou sendo
mais útil que o caminho feliz.


---

## O build da imagem quebrou em produção — e por quê

O `Dockerfile` multi-stage entregue em 12/08 **nunca foi buildado** — não havia
docker na máquina de desenvolvimento, e isso estava registrado como não
verificado. No primeiro deploy real, 16/08:

```
sh: 1: uvicorn: not found
```

O container novo reiniciava em loop enquanto o antigo seguia servindo. O sintoma
externo era pior que uma falha limpa: o painel mostrava o commit novo, a
aplicação não mudava, e nada indicava erro para quem olhasse só a URL.

### A causa

**Venv em Python não é relocável.** Os scripts em `bin/` nascem com shebang
absoluto apontando para o interpretador do venv. O build criava em `/build/venv`
e copiava para `/app/venv`, deixando `/app/venv/bin/uvicorn` com:

```
#!/build/venv/bin/python
```

Caminho que não existe na imagem final. O arquivo está lá; falta o interpretador
que ele invoca — e o shell reporta isso como `not found`, o que manda procurar no
lugar errado.

### A correção

Duas mudanças, cada uma suficiente sozinha; juntas por segurança.

**O venv passa a ser criado no caminho final**, `/app/venv`, já no estágio de
build. Origem e destino iguais, shebang correto.

**O `CMD` usa `python -m uvicorn`** em vez de chamar o script. Isso não depende
do shebang, só do interpretador — um venv movido continua funcionando por esse
caminho, e a falha, se houver, vira um `ImportError` que diz o nome do módulo.

### O que isso ensina sobre o resto

Era o único item da lista de "não verificado" que dependia de infraestrutura
indisponível no ambiente de desenvolvimento. Ele quebrou. Os demais itens dessa
lista merecem o mesmo ceticismo — em especial o build check do `.dockerignore`,
que continua sem execução real.


### Segundo erro do mesmo deploy: `Could not import module "main"`

Corrigido o venv, o uvicorn passou a rodar — e parou no import:

```
ERROR: Error loading ASGI app. Could not import module "main".
```

**Os dois Dockerfiles esperam o contexto de build na RAIZ do repositório.** Era
assim desde o início: o `server/Dockerfile` original tinha `COPY server/ .`,
idêntico ao da raiz, e há um commit antigo do projeto registrando "suporte a
context raiz e subpasta server".

Numa sincronização entre os dois arquivos, os caminhos do `server/Dockerfile`
foram ajustados supondo contexto = `server/`, trocando o `COPY server/ .` por
`COPY . .`.

| Contexto | Dockerfile | Onde cai o `main.py` |
|---|---|---|
| raiz | raiz | `/app/main.py` ✅ |
| `server/` | `server/` | `/app/main.py` ✅ |
| **raiz** | **`server/`** | `/app/server/main.py` ❌ |

O deploy usa a terceira combinação. O uvicorn procura `main` em `/app` e não
acha, porque o arquivo foi parar um nível abaixo.

**Correção:** `server/Dockerfile` voltou a ser cópia exata do da raiz, com uma
nota no topo explicando que divergir os dois foi o que causou o incidente.

### O padrão dos dois erros

Os dois estavam em código que o ambiente de desenvolvimento não conseguia
executar: sem Docker disponível, um `Dockerfile` só pode ser revisado, nunca
testado. Nenhum dos dois é visível na leitura — o shebang do venv e o destino do
`COPY` só se manifestam quando a imagem roda. Um único `docker build` local
pegaria ambos em segundos.

É a diferença entre revisar e verificar, e é o motivo de a lista de "não
verificado" deste documento merecer ser levada a sério em vez de tratada como
formalidade. Quem assumir com Docker à mão elimina essa classe inteira de erro
antes do primeiro deploy.
