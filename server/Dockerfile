# Este arquivo e IDENTICO ao Dockerfile da raiz, de proposito.
#
# Ambos esperam o contexto de build na RAIZ do repositorio — e por isso o
# `COPY server/ .` existe nos dois. Foi assim desde o inicio; um commit antigo
# do projeto registra "suporte a context raiz e subpasta server".
#
# Ja houve uma sincronizacao que ajustou os caminhos deste arquivo supondo
# contexto = server/, trocando por `COPY . .`. Isso quebra a combinacao que o
# deploy usa (contexto raiz + este Dockerfile): o main.py cai em
# /app/server/main.py enquanto o uvicorn procura em /app, e o sintoma e
# `Error loading ASGI app. Could not import module "main"`.
#
# Se precisar mexer, mexa no da raiz e copie para ca. Divergir os dois e o que
# reintroduz esse erro.

# ── Build ────────────────────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

# O venv e criado em /app/venv, o MESMO caminho que tera na imagem final.
#
# Nao e detalhe de organizacao: venv em Python NAO e relocavel. Os scripts em
# bin/ nascem com shebang absoluto apontando para o interpretador do venv. Criar
# em /build/venv e copiar para /app/venv deixa /app/venv/bin/uvicorn com shebang
# #!/build/venv/bin/python — caminho que nao existe na imagem final.
#
# O sintoma engana: `sh: 1: uvicorn: not found`. O arquivo esta la; o que falta e
# o interpretador que ele invoca, e o shell reporta isso como se o script nao
# existisse. E caro de diagnosticar em producao: o container novo reinicia em
# loop enquanto o antigo segue servindo, entao a aplicacao apenas "nao atualiza",
# sem erro visivel para quem acompanha de fora.
WORKDIR /app

COPY server/requirements.txt* requirements.txt* ./
RUN python -m venv /app/venv \
 && /app/venv/bin/pip install --no-cache-dir --upgrade pip setuptools \
 && /app/venv/bin/pip install --no-cache-dir -r requirements.txt

# O servidor-gerente NAO abre browser: usa from_storage (cookies) + RPC HTTP.
# O login com Chromium acontece so no cliente (connect.py). Por isso nao
# instalamos Playwright/Chromium aqui — build mais rapido e imagem menor.

# ── Runtime ──────────────────────────────────────────────────────────────────────
FROM python:3.13-slim

WORKDIR /app

# Usuario sem privilegio. O processo nao precisa de root: nao escreve em disco,
# nao instala nada, e a porta 80 e publicada pelo proxy do EasyPanel — quem
# escuta dentro do container nao precisa ser root para isso.
RUN groupadd --system appuser \
 && useradd --system --uid 1000 --gid appuser --create-home appuser

# Mesmo caminho de origem e destino — ver a explicacao no estagio de build.
COPY --from=builder --chown=appuser:appuser /app/venv /app/venv

# O .dockerignore mantem .env, .git, client/ e scripts/ fora do contexto.
# Confira antes de publicar em registry (ver DEPLOY.md, secao 4).
COPY --chown=appuser:appuser server/ .
COPY --chown=appuser:appuser . .

ENV PATH="/app/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

# /health e nao /mcp: o /mcp responde 401 por design (OAuth), o que um
# healthcheck leria como servidor doente. urllib e da stdlib — `requests` nao
# esta no requirements, e um HEALTHCHECK que importa modulo ausente falha
# sempre, marcando o container unhealthy para todo o sempre.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:80/health', timeout=5).status == 200 else 1)"

EXPOSE 80

# `python -m uvicorn` em vez de `uvicorn`: nao depende do shebang do script em
# bin/, so do interpretador. Um venv movido continua funcionando por este
# caminho, e a falha, se houver, e um ImportError que diz o nome do modulo.
#
# ATENCAO ao mexer aqui: o rate limit por-usuario do MCP (_rate_ok em
# mcp_server.py) conta em memoria, POR PROCESSO. Sem --workers, o uvicorn sobe
# 1 worker e o limite de NOTEBOOKLM_MCP_RATE_PER_MIN vale de verdade.
# Adicionar `--workers N` multiplica o limite efetivo por N, sem erro e sem log.
# Se precisar escalar, troque antes o rate limit por um backend compartilhado.
# Aplica o schema (idempotente, so CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT
# EXISTS) antes de subir o servidor, para que migracoes como notebooklm.bot_links
# existam mesmo em um deploy novo sem passo manual. Falha de schema interrompe o
# start (fail-fast) em vez de subir a API contra um banco desatualizado.
CMD ["sh", "-c", "python db/apply_schema.py && python -m uvicorn main:app --host 0.0.0.0 --port 80 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
