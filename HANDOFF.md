# Handoff — NotebookLM Connector

Documento de transferência. Escrito para quem vai assumir o projeto sem ter
participado da construção.

> **Estado da entrega:** fecha em F1, F2 e a tool 11 de F4 do `ESCOPO.md`
> (mais o vínculo por bot, adicional fora do escopo original). F3 inteira e a
> tool 12 de F4 não foram construídas porque o contrato não avançou até essas
> fases — não é pendência técnica esquecida. Ver "Encerramento desta entrega"
> no fim do `ESCOPO.md` para o detalhe.

## O que este repositório é

Um servidor que expõe o acervo do NotebookLM da organização (~277 notebooks) como
ferramenta do Claude, com login Google por pessoa, nível de acesso por função e
auditoria de todas as consultas.

Duas interfaces sobre o mesmo núcleo:

- **`/mcp`** — conector MCP, autenticado por OAuth Google. É como os advogados usam.
- **`/api`** — REST com token Bearer por usuário. É como o n8n consome.

A arquitetura, os endpoints e o modelo de níveis estão no `README.md`. O passo a
passo de instalação está no `DEPLOY.md`, em 9 passos, e **a ordem importa** —
inverter os primeiros derruba o login de toda a equipe. A rotina de conceder e
revogar acesso às pessoas está no `ACESSOS.md`.

**Se você acabou de receber este projeto, comece pelo `GUIA-DA-CONSULTORIA.md`** —
ele dá a ordem de leitura, a ordem de trabalho e o mapa das armadilhas, e aponta
de volta para cá.

O `GUIA-DO-DOUTOR.md` é a versão sem termos técnicos, endereçada ao Doutor. Vale
ler antes da primeira conversa com ele: é o que ele já sabe sobre o estado da
entrega, incluindo o que **não** foi construído.

---

## Este repositório vem sem credenciais. De propósito.

Nada de segredo foi transferido: nem chave de criptografia, nem senha de banco,
nem cliente OAuth, nem os tokens Google dos advogados.

Não é omissão — é o desenho correto. Uma chave que viaja entre organizações
deixa de proteger o que cifra. A equipe que assume gera as suas.

O que precisa ser provisionado antes do primeiro deploy:

| Item | Como obter |
|---|---|
| Chave Fernet | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| Postgres | verificar se há instância aproveitável no ambiente do escritório — ver `DEPLOY.md`, seção 0; schema via `python server/db/apply_schema.py` |
| Cliente OAuth Google | criar no Google Cloud da organização, com `redirect_uri = https://<host>/auth/callback` |
| `PUBLIC_URL` | a URL pública do deploy — **obrigatória, sem default** |

O `server/.env.example` documenta cada variável. As três obrigatórias
(`NOTEBOOKLM_ENCRYPTION_KEY`, `DATABASE_URL`, `PUBLIC_URL`) fazem o servidor
recusar subir se faltarem — deliberado, para que um deploy mal configurado falhe
alto em vez de funcionar errado.

### Os advogados vão refazer o cadastro

Os tokens Google ficaram no ambiente antigo. Cada pessoa roda `client/connect.py`
uma vez no ambiente novo, e um admin ativa. O procedimento está no `README.md`.

O primeiro admin é bootstrap direto no banco (`server/db/gen_token.py`) — não há
como emitir token de admin sem um admin.

### Sem classificar os notebooks, a equipe não vê nada

O filtro por área é **fail-closed**: notebook sem classificação é invisível para
os níveis `juridico` e `financeiro`. Só `admin` e `gestor` enxergam tudo.

É inconveniência deliberada no lugar de vazamento — mas significa que, num
ambiente recém-instalado, a equipe abre o Claude e vê lista vazia até
`scripts/classifica_notebooks.py` rodar. Não é bug.

---

## Riscos conhecidos

Nenhum destes é impeditivo. Todos são surpresa desagradável se descobertos
depois, então estão aqui.

**A biblioteca do NotebookLM não é oficial.** O `notebooklm-py` é engenharia
reversa da aplicação web. Não há SLA nem compromisso de compatibilidade — o
Google pode mudar algo e quebrar o conector sem aviso. Risco aceito e registrado
no `ESCOPO.md`.

**O rate limit conta em memória, por processo.** Está correto porque o
`Dockerfile` sobe **um** worker uvicorn. Adicionar `--workers N` multiplica o
limite efetivo por N, silenciosamente — sem erro e sem log. Há um aviso no
próprio `Dockerfile`, ao lado do `CMD`. Escalar horizontalmente exige trocar
antes por um backend compartilhado.

**TLS no Postgres depende do servidor suportar.** O código exige `sslmode=require`
quando não especificado, mas instâncias EasyPanel sobem sem TLS configurado — e
aí `require` impede a conexão em vez de proteger. O desenho correto é app e banco
no mesmo projeto, comunicando por nome de serviço interno, com o tráfego nunca
saindo do host. O que não fecha é `sslmode=disable` **com host público**.

**O `audit_log` guarda pergunta e resposta.** Cifrado com Fernet — mas com a
chave do servidor. Quem opera o servidor consegue ler consultas jurídicas sobre
casos de clientes da organização. É dado sob sigilo profissional; a gestão de
acesso ao servidor e ao banco precisa refletir isso.

**`db.py` não tem cobertura de teste.** É onde estão as garantias mais fáceis de
quebrar sem perceber numa refatoração, porque nenhuma delas dá erro visível
quando quebra:

- o single-use do token de onboarding depende de um `UPDATE … WHERE usado_em IS
  NULL RETURNING` ser atômico; refatorar para SELECT-depois-UPDATE vira TOCTOU
- o `ON CONFLICT DO UPDATE` que não toca em `nivel`/`ativo` é o que impede
  alguém de se auto-promover reenviando o upload
- o fail-secure do `sslmode`

**O teto global de requisições vive em memória, por processo** — mesma ressalva
do rate limit por usuário, e some se alguém adicionar `--workers N`.

> Este item já foi um defeito mais grave: o rate limit da REST não contava
> chamadas **não autenticadas**, porque o `Depends` da autenticação resolve antes
> do contador do `slowapi`. Verificado contra deploy real na época — 13
> requisições sem credencial em `/api/auth/check`, nenhum `429`. Corrigido com o
> `TetoGlobalMiddleware` em `api.py`, que conta por IP antes de qualquer
> dependência. `server/tests/test_rate_limit.py` cobre os quatro casos,
> incluindo requisição sem credencial e a isenção do `/health`.

**O check de vazamento da imagem ainda não foi executado.** A imagem builda e
roda — o deploy sobe a partir dela. O que falta é a verificação de que `.env` e
`.git` ficaram de fato fora das camadas, que exige Docker à mão e não estava
disponível no ambiente de desenvolvimento. Antes de publicar em qualquer
registry, rode o check do `DEPLOY.md` seção 4.

---

## O que já está pronto e verificado

| Item | Estado |
|---|---|
| Testes | 44 passando, ~2s, verificados por mutação |
| Container | usuário sem privilégio (uid 1000) |
| `HEALTHCHECK` | `urllib` contra `/health`, testado nos dois sentidos |
| `.dockerignore` | `.env`, `.git`, `client/`, `scripts/` fora da imagem |
| `PUBLIC_URL` | obrigatória, sem default apontando para outro deploy |
| `audit_log` / `access_log` | append-only por trigger no banco, não só no código |
| Hosts | nenhum hardcoded em código, docs ou no bundle `.skill` |
| Comportamento HTTP | recusas e limites observados em deploy real — `docs/VERIFICACAO.md` |
| Imutabilidade do log | 10/10 contra banco real: `UPDATE`, `DELETE` e `TRUNCATE` recusados |

"Verificado por mutação" quer dizer: desligamos a proteção no código de
produção e confirmamos que a suíte detecta. Medido sobre as 44:

| Proteção desligada | Testes que quebram |
|---|---|
| Fail-closed do acesso a notebook por ID | 6 |
| Validação da chave Fernet | 9 |
| Fail-closed da listagem | 1 |
| Recusa de e-mail Google não verificado | 1 |

Nenhuma delas passa despercebida — que é o ponto.

Verde sozinho não prova nada. Uma suíte pytest passa sem ter executado o que
interessa em pelo menos três situações — teste async ignorado por falta de
`asyncio_mode`, arquivo que coleta zero testes por caminho de import errado, e
mock no alvo errado que cai no código real. O `pytest.ini` e o `conftest.py`
fecham as três; o critério de mutação é o que garante que continuem fechadas.

```bash
pip install -r server/requirements.txt -r server/requirements-dev.txt
pytest
```

---

## Sobre o histórico do git

Este repositório começa num commit único. O histórico anterior — 63 commits da
construção — não foi transferido, por dois motivos: continha valores de
credenciais já rotacionadas, e não tem valor para quem assume. O que vale é o
estado final mais esta documentação.

---

## Próximo passo sugerido

Antes de qualquer feature nova, cobrir o `db.py`. A infraestrutura de teste já
está pronta: `pytest.ini`, `conftest.py` com as variáveis de ambiente e um
fixture que bloqueia conexão real com o Postgres — ele falha na hora, com
mensagem explicando onde procurar, se algum mock estiver no alvo errado.

Vale seguir o mesmo critério de aceite: não basta ficar verde, tem que quebrar
quando a proteção é desligada.
