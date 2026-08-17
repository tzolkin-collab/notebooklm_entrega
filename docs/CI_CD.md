# CI — pipeline sugerido

> **Status: não instalado.** Este documento é um template pronto para copiar,
> não a descrição de algo que já roda. O arquivo `.github/workflows/` não está
> no repositório porque o push foi recusado — o token usado não tinha o escopo
> `workflow`. Instalar é o passo 1 abaixo.

O que existe hoje: a suíte de testes roda localmente (`pytest`, 26 testes,
~2s). O que falta: rodar sozinha a cada push.

---

## 1. Instalar

Criar `.github/workflows/ci.yml` com o conteúdo abaixo. O push precisa de um
token com escopo `workflow` — pelo `gh` autenticado (`gh auth refresh -s
workflow`) ou pela interface do GitHub, que não tem essa restrição.

```yaml
name: CI

on:
  push:
    branches: [master, "deploy/**", "test/**", "hardening/**"]
  pull_request:

jobs:
  test:
    name: pytest
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip

      - run: pip install -r server/requirements-dev.txt

      # requirements-dev.txt ja puxa o requirements.txt via `-r`.
      # pytest.ini cuida de pythonpath e asyncio_mode — nao passe flags aqui.
      - run: pytest

  imagem:
    name: build + segredos fora da imagem
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - run: docker build --tag notebooklm:ci .

      # Este e o check que nao deu para rodar na maquina de desenvolvimento.
      # O Dockerfile faz `COPY . .`; se o .dockerignore parar de cobrir .env ou
      # .git, a imagem passa a carregar chave Fernet, senha do Postgres e o
      # historico do git — que tem commits removendo API keys.
      - name: .env e .git nao podem estar na imagem
        run: |
          if docker run --rm notebooklm:ci sh -c 'ls /app/.env' 2>/dev/null; then
            echo "::error::.env entrou na imagem"; exit 1
          fi
          if docker run --rm notebooklm:ci sh -c 'ls -d /app/.git' 2>/dev/null; then
            echo "::error::.git entrou na imagem"; exit 1
          fi
          echo "ok: nenhum dos dois esta na imagem"

      - name: container nao roda como root
        run: |
          U=$(docker run --rm notebooklm:ci whoami)
          [ "$U" = "appuser" ] || { echo "::error::rodando como $U"; exit 1; }
          echo "ok: $U"

  dependencias:
    name: vulnerabilidades conhecidas
    runs-on: ubuntu-latest
    continue-on-error: true    # informativo: reporta, nao bloqueia merge
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install pip-audit
      - run: pip-audit -r server/requirements.txt --desc
```

---

## 2. O que cada job cobre

| Job | Cobre | Bloqueia merge |
|---|---|---|
| `test` | os 26 testes de auth e access control | sim |
| `imagem` | build + `.env`/`.git` fora da imagem + non-root | sim |
| `dependencias` | CVEs conhecidas no requirements | não |

O job `imagem` é o mais importante dos três, porque é o único check deste
repositório que **não pode ser feito na máquina de desenvolvimento** — exige
docker. Enquanto ele não existir, a garantia de que a imagem não carrega
segredo depende de alguém lembrar de rodar o comando manualmente antes de
publicar (`DEPLOY.md`, seção 4).

---

## 3. Rodar localmente antes do push

```bash
pip install -r server/requirements-dev.txt
pytest

docker build --tag notebooklm:local .
docker run --rm notebooklm:local sh -c 'whoami; ls -la /app/.env 2>&1; ls -d /app/.git 2>&1'
```

Esperado no segundo comando: `appuser`, e `No such file or directory` nas duas
listagens.

---

## 4. Branch protection

Depois que o workflow rodar pelo menos uma vez, os checks aparecem em
*Settings → Branches → Add rule*. Marcar como obrigatórios:

- `pytest`
- `build + segredos fora da imagem`

Não marcar `vulnerabilidades conhecidas`: um CVE novo em dependência
transitiva travaria merge de coisa não relacionada. Ele serve para ser lido,
não para bloquear.

---

## Fora do escopo

Coisas que fazem sentido depois, mas que não vale adicionar antes do pipeline
básico estar rodando e sendo respeitado:

- cobertura com limiar mínimo (a suíte ainda não cobre `db.py` — ver #10)
- SAST (bandit, SonarQube)
- scan de imagem (Trivy)
- Dependabot
- deploy automático pós-merge
