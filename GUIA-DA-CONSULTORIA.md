# Comece aqui — consultoria técnica

Você está assumindo um projeto que não construiu. Este documento é a ordem de
leitura e de trabalho; ele **não** repete os runbooks, aponta para eles.

| Onde ir depois | Para quê |
|---|---|
| `HANDOFF.md` | o que o repositório é, riscos conhecidos |
| `DEPLOY.md` | os 9 passos da instalação — a ordem importa |
| `ACESSOS.md` | conceder e revogar acesso, depois de no ar |
| `README.md` | arquitetura, endpoints, modelo de níveis |
| `docs/VERIFICACAO.md` | o que foi observado contra deploy real |
| `GUIA-DO-DOUTOR.md` | o que o cliente já sabe — leia antes da primeira reunião |

---

## Em cinco minutos: o que é isto

Um servidor que expõe o acervo NotebookLM do escritório (~277 notebooks) como
ferramenta do Claude, com login Google por pessoa, nível de acesso por função e
auditoria de todas as consultas.

Duas interfaces sobre o mesmo núcleo: **`/mcp`** (conector MCP, OAuth Google — é
como os advogados usam) e **`/api`** (REST com Bearer por usuário — é como uma
automação consumiria).

Python 3.13, FastAPI + FastMCP, Postgres, um container. Sem fila, sem cache, sem
serviço auxiliar. A simplicidade é proposital: o que existe cabe na cabeça de uma
pessoa numa tarde.

---

## O estado real

Sem otimismo. Cada linha abaixo é verificável no repositório.

### Pronto e verificado

| Item | Como foi verificado |
|---|---|
| 44 testes, ~2s | verificados **por mutação** — ver abaixo |
| Imutabilidade do log | 10/10 contra banco real: `UPDATE`, `DELETE` e `TRUNCATE` recusados por trigger |
| Container sem privilégio | `appuser` uid 1000, `USER appuser` no `Dockerfile` |
| `HEALTHCHECK` | `urllib` contra `/health`, testado nos dois sentidos |
| `.dockerignore` | `.env`, `.git`, `client/`, `scripts/` fora da imagem |
| `PUBLIC_URL` obrigatória | sem default; o servidor recusa subir sem ela |
| Teto de requisições | conta por IP **antes** da autenticação; 4 testes cobrem, incluindo chamada sem credencial |

**"Verificado por mutação"** quer dizer: desligamos a proteção no código de
produção e confirmamos que a suíte detecta. Medido sobre as 44:

| Proteção desligada | Testes que quebram |
|---|---|
| Fail-closed do acesso a notebook por ID | 6 |
| Validação da chave Fernet | 9 |
| Fail-closed da listagem | 1 |
| Recusa de e-mail Google não verificado | 1 |

Nenhuma delas passa despercebida — que é o ponto.

Isso importa mais do que parece: **uma suíte pytest pode ficar verde sem ter
executado o que interessa.** Três formas de acontecer, todas silenciosas:

- teste async coletado e ignorado, por falta de `asyncio_mode`
- arquivo que coleta zero testes, por caminho de import errado
- mock no alvo errado, que cai no código real e trava até o timeout do driver

O `pytest.ini` e o `conftest.py` deste repositório fecham as três. Mantenha o
critério de mutação junto: não basta passar, tem que **quebrar** quando a
proteção é removida — é ele que detecta se alguma dessas portas reabrir.

### Ainda sem verificação

**O check de vazamento de segredo na imagem.** A imagem builda e roda — o deploy
sobe a partir dela. O que nunca foi executado é a conferência de que `.env` e
`.git` ficaram de fato fora das camadas, porque exige Docker à mão e ele não
estava disponível no ambiente de desenvolvimento. É a **primeira coisa** a fazer:

```bash
docker build --tag notebooklm:deploy .
docker run --rm notebooklm:deploy sh -c 'whoami; ls -la /app/.env 2>&1; ls -d /app/.git 2>&1'
```

Esperado: `appuser` e `No such file or directory` nas duas. Se `.env` ou `.git`
aparecerem, a imagem carrega a chave Fernet e a senha do banco — não publique.

### Não existe

| Faltando | Onde estava previsto |
|---|---|
| `gerar_relatorio`, `gerar_podcast`, `baixar_artefato` | fase 3 do `ESCOPO.md` |
| `historico` (ler a auditoria pelo Claude) | fase 4 |
| Renovação agendada dos tokens Google | fase 4 |
| Cobertura de teste em `db.py` | — |

Verificado por busca no `server/`: zero ocorrências das quatro primeiras. **O
cliente já foi informado** — está no `GUIA-DO-DOUTOR.md`.

No `ESCOPO.md`, a fase 3 aparece como a de maior valor percebido pelo cliente.
É a candidata natural a primeira entrega nova, e a base para ela já existe: as
tools de artefato do `notebooklm-py` seguem o mesmo padrão das que estão
implementadas.

Existem **12 ferramentas MCP** registradas, incluindo as de compartilhamento, que
eram fase 4. Confira em `server/mcp_server.py`.

---

## Três decisões antes de tocar em qualquer coisa

### 1. A chave Fernet é nova. Não é negociável.

A chave que existia passou por mãos de outra empresa durante o desenvolvimento.
Gere uma nova mesmo que encontre a antiga já configurada no ambiente.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Reaproveitar o Postgres existente, ou não?

A infraestrutura do escritório **já existe** — não é deploy do zero. Se houver um
banco do ambiente anterior:

- **A favor de manter:** ele carrega o `audit_log` histórico, que é registro de
  consulta sob sigilo profissional. Descartar por conveniência de implantação é
  uma escolha que alguém deveria fazer conscientemente.
- **Contra:** os `tokens` nele estão cifrados com a chave antiga e ficam
  ilegíveis com a nova. Na prática custa pouco — a equipe refaz o login de
  qualquer forma.

Decisão do cliente, não do implantador.

### 3. `FORWARDED_ALLOW_IPS`

Sem isso, atrás do proxy toda requisição chega com o IP do proxy e o teto de
requisições vira um balde único compartilhado por todo mundo — o primeiro
usuário ativo derruba os demais. Ponha a faixa do proxy. **Nunca `*`**: com
curinga, o `X-Forwarded-For` passa a ser aceito de qualquer origem, e ele é
enviado *pelo cliente*.

---

## A ordem do trabalho

1. **Rodar a suíte.** Antes de qualquer deploy, para saber que a base está sã.
   ```bash
   pip install -r server/requirements.txt -r server/requirements-dev.txt
   pytest
   ```
   Esperado: 44 passando em ~2s. Não passe flags — o `pytest.ini` já cuida de
   `pythonpath` e `asyncio_mode`.

2. **Buildar a imagem e rodar o check de vazamento** (acima). Nunca foi feito.

3. **Seguir o `DEPLOY.md`, na ordem.** Os passos 2 e 3 invertidos derrubam o
   login de toda a equipe.

4. **Validar** com os `curl` do `DEPLOY.md` seção 5. O `issuer` no metadata OAuth
   tem que ser o host do escritório — se aparecer outro, o `PUBLIC_URL` está
   errado, e o login da equipe passaria por um servidor que não é o deles.

5. **Bootstrap do primeiro admin** direto no banco. Não há como emitir token de
   admin sem um admin.

6. **Classificar os notebooks.** Sem isso o fail-closed deixa `juridico` e
   `financeiro` vendo lista vazia, e o escritório inteiro acha que está quebrado.
   O cliente já foi avisado disso, mas ele vai ligar mesmo assim.

7. **Onboarding da equipe** — `ACESSOS.md`.

---

## Onde estão as armadilhas

Nenhuma destas é precaução teórica — todas já se manifestaram em execução real,
e por isso estão comentadas no próprio código, no ponto onde importam.

**O venv não é relocável.** Criar em `/build/venv` e copiar para `/app/venv`
deixa os scripts em `bin/` com shebang apontando para um caminho que não existe
na imagem final. O sintoma engana: `sh: 1: uvicorn: not found` — o arquivo está
lá, o que falta é o interpretador que ele invoca. Por isso o `Dockerfile` cria o
venv já em `/app/venv`, e o `CMD` usa `python -m uvicorn` em vez de `uvicorn`.

**Os dois `Dockerfile` esperam contexto = raiz do repositório.** Tanto o da raiz
quanto o de `server/`. "Ajustar os caminhos" de um deles supondo contexto
`server/` quebra a combinação que o deploy usa, com
`Could not import module "main"`. Se precisar mexer, mexa no da raiz e copie.

**`TRUNCATE` não é coberto por `BEFORE UPDATE OR DELETE`.** O append-only do
`audit_log` passou 8/10 até isso aparecer; trigger de TRUNCATE exige
`FOR EACH STATEMENT`. Verificado 10/10 depois da correção, contra banco real.

**`Depends` resolve antes do corpo da rota.** Por isso um `@limiter.limit()` não
protege chamada não autenticada: a dependência de autenticação já rejeitou antes
de o contador rodar. E `SlowAPIMiddleware` não conserta — o `_should_exempt` do
slowapi pula deliberadamente rotas que têm o decorator. A saída foi um
middleware próprio (`TetoGlobalMiddleware`), que conta antes de tudo.

**`asyncio_mode = auto` no `pytest.ini` é o que faz os testes async rodarem.**
Sem ele, pytest coleta e ignora com warning. Suíte verde, nada executado.

**Dependência invocada por subprocesso não aparece como `import`.** O
`notebooklm-py` ficou fora do `client/requirements.txt` por isso, e o onboarding
só funcionava em máquina que já tivesse as dependências do servidor. Uma
verificação baseada em imports não pega esse caso.

**`pythonw` engole erro de import.** No cliente, `start "" pythonw` desanexa o
processo e descarta o stderr: faltando uma dependência, a janela não abre e nada
aparece. O `.bat` e o `admin.pyw` têm guardas para isso — mantenha-as se mexer.

**`_db_params()` descarta parâmetros de query.** Em `db.py`, tudo exceto
`sslmode` é silenciosamente ignorado: `connect_timeout`, `application_name` e
afins precisam ir no dicionário de conexão, não na URL.

---

## Primeira coisa depois de estar no ar

**Cobrir `db.py` com testes.** É onde estão as garantias mais fáceis de quebrar
numa refatoração sem que nada dê erro visível:

- o single-use do token de onboarding depende de um `UPDATE … WHERE usado_em IS
  NULL RETURNING` ser atômico; refatorar para SELECT-depois-UPDATE vira TOCTOU
- o `ON CONFLICT DO UPDATE` que **não** toca em `nivel`/`ativo` é o que impede
  alguém de se auto-promover reenviando o upload
- o fail-secure do `sslmode`

A infraestrutura já está pronta: `conftest.py` tem um fixture que bloqueia
conexão real com o Postgres e falha na hora, com mensagem, se algum mock estiver
no alvo errado. Foi ele que levou a suíte de 4m23s para 2s.

**Depois disso**, a renovação agendada dos tokens Google. Sem ela alguém vai
refazer o onboarding manualmente para sempre, e é a diferença entre o sistema
funcionar e funcionar sem ninguém precisar pensar nele.

---

## Duas ressalvas que não são bug

**O acervo é dado sob sigilo profissional.** O `audit_log` guarda pergunta e
resposta cifradas — mas com a chave do servidor. Quem opera o servidor consegue
ler consultas jurídicas sobre casos de clientes do escritório. O acesso ao
servidor e ao banco precisa ser tratado com esse critério.

**A biblioteca do NotebookLM não é oficial.** `notebooklm-py` é engenharia
reversa da aplicação web. Não há SLA nem compromisso de compatibilidade: o Google
pode mudar algo e quebrar o conector sem aviso. Risco aceito e registrado desde o
`ESCOPO.md`. Se um dia parar do nada, comece por aí.

---

## Sobre este repositório

Começa num commit único. O histórico anterior não foi transferido: continha
valores de credenciais já rotacionadas, e não tem valor para quem assume. O que
vale é o estado final mais esta documentação.

Nenhum segredo foi transferido — nem chave de criptografia, nem senha de banco,
nem cliente OAuth, nem os tokens Google dos advogados. É o desenho correto, não
omissão.
