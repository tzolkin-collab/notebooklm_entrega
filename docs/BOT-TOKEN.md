# Recebimento da sessao Google pelo bot

O token recebido e o JSON `storage_state` (cookies da sessao NotebookLM),
nao o Bearer da API nem um access token OAuth. O fluxo antigo
`/api/token/upload` continua intacto para onboarding.

## Configuracao

### Arquivos locais prontos para preencher

- `server/.env`: DATABASE_URL e PUBLIC_URL do servidor; nova
  NOTEBOOKLM_BOT_CALLBACK_KEY. Os outros campos sao as credenciais EXISTENTES
  do servidor para o deploy. Nao substituir a chave Fernet do banco atual.
- `scripts/bot/.env`: NOTEBOOKLM_SERVER_URL igual a PUBLIC_URL e a mesma
  NOTEBOOKLM_BOT_CALLBACK_KEY. O bot nunca recebe a chave Fernet nem acesso ao banco.

Ambos os arquivos `.env` sao ignorados pelo Git e excluidos do Docker.
Estes arquivos locais nao atualizam as envs do EasyPanel/bot em producao.

Validacao sem rede: `.venv-testes/Scripts/python.exe scripts/configure_bot.py`.
Depois do preenchimento e confirmacao, executar o mesmo comando com `--apply`.
Ele aplica apenas `server/db/bot_links.sql`, em transacao, com timeouts e sem
imprimir credenciais. Exige TLS para a conexao remota ao banco.

O adaptador `scripts/bot/send_token.py` expoe `send_token(link_token,
google_account, storage_state)` para integrar no backend do bot. Tambem aceita
`--storage-state <arquivo>` para envio manual: solicita o codigo sem eco no
terminal. Nao segue redirects e nao imprime cookies ou respostas de erro.
Ele nao implementa o login/captura do bot externo.

1. Aplicar `server/db/schema.sql` no banco existente (idempotente), para criar
   `notebooklm.bot_links`. Nao ha migracao automatica no boot.
2. Configurar `NOTEBOOKLM_BOT_CALLBACK_KEY` no servidor e no backend do bot,
   com o mesmo segredo aleatorio de pelo menos 32 bytes. Sem env, o fluxo fica
   desabilitado. Nao colocar essa chave no cliente, conversa MCP ou URL.
3. Manter `PUBLIC_URL` com a URL HTTPS publica deste servidor e fazer o deploy.

## Fluxo

1. Usuario ja cadastrado e ativo chama `criar_vinculo_bot` no MCP autenticado,
   ou `POST /api/token/link` com `Authorization: Bearer <bearer-do-usuario>`.
   Nao ha parametro de email. A identidade vem da autenticacao existente.
2. Resposta: `link_token`, `expires_in: 600` e `callback_url`.
   Entregar o codigo somente ao bot confiavel. Ele autoriza uma unica troca
   de sessao e e armazenado apenas como hash SHA-256 no Postgres.
3. O bot captura a sessao apos o login Google e identifica a conta efetivamente
   selecionada no navegador (nao copiar um email informado no chat).
4. Backend do bot envia `POST <PUBLIC_URL>/api/bot/token`, com
   `Content-Type: application/json` e `X-Bot-Key: <segredo-da-env>`:

```json
{
  "link_token": "<codigo-recebido-do-usuario>",
  "google_account": "usuario@exemplo.com",
  "storage_state": {
    "cookies": [
      {"name": "SID", "value": "<cookie-real>", "domain": ".google.com", "path": "/"}
    ],
    "origins": []
  }
}
```

Enviar o estado completo do navegador; o exemplo e apenas estrutural.
Nao enviar `email`, `nivel`, `ativo` ou outros campos no corpo.

5. O servidor resolve o destino pelo codigo no banco, exige usuario ainda ativo
   e conta Google reportada igual ao cadastro (ignorando maiusculas/espacos nas
   extremidades do valor reportado). Consome o codigo, cifra com Fernet e grava
   sessao + auditoria na mesma transacao. Nao cria usuarios, ativa contas nem
   rotaciona Bearers. Retorna `{"status":"ok","email":"usuario@exemplo.com"}`.

## Erros e limites

- 400: JSON/estado malformado ou campos extras; codigo nao consumido.
- 401: chave do bot ausente/incorreta.
- 403: codigo expirado/usado/invalido, conta divergente ou usuario inativo.
- 413: corpo acima de 1 MiB.
- 429: limite de requisicoes; repetir mais tarde se o codigo ainda for valido.
- 503: env da integracao ausente.

Se a gravacao falhar, a transacao desfaz o consumo. Um callback ja concluido
nao pode ser repetido: se a resposta se perder, verificar `/api/auth/check`
com o Bearer do usuario antes de gerar outro vinculo. Codigos expiram em
10 minutos, inclusive apos reinicios, pois estao no banco.

## Fronteira de confianca

O servidor valida a estrutura e os dominios dos cookies, mas **nao verifica
online a identidade Google nem a validade da sessao** neste callback.
`google_account` e atestado pelo backend do bot autenticado. A chave da env
identifica esse backend; o codigo define qual conta ele pode atualizar.
Nao compartilhar cookies no chat, nem registrar corpos, headers ou codigos
nos logs do bot/proxy. O MCP transporta so o codigo temporario, nao cookies.

Este fluxo exige cadastro ativo; primeiro acesso continua passando pelo
onboarding/admin existente. A implementacao nao inclui a captura de login ou
o envio no bot externo: ele precisa seguir o contrato acima. Nenhum deploy
ou alteracao no banco de producao e executado automaticamente.
