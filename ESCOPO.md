# NotebookLM Connector — Escopo do produto (v1.0)

> Definido em 2026-06-11. Este documento fecha o escopo do produto.
> Mudanças daqui em diante são change request, não escopo.

## Visão

Assistente jurídico da organização dentro do Claude:
a equipe consulta o acervo do NotebookLM (≈277 notebooks — contencioso,
consultas, LGPD, diretoria) com citações, gera artefatos (relatórios,
podcasts) e administra fontes — tudo com identidade Google, nível de acesso
por função e auditoria completa.

## Arquitetura (inalterada)

- **Servidor** (EasyPanel): FastMCP (OAuth Google) em `/mcp` + FastAPI REST em `/api`.
  Postgres `notebooklm.*`: `users`, `tokens` (Fernet), `notebooks`, `audit_log`.
- **Cliente local** `connect.py`: onboarding self-service de token Google.
- **Plugin Claude** `aaa-notebooklm` (SKILL.md + references), distribuído como `.skill`.

## Modelo de segurança (fechado)

1. Identidade: OAuth Google no MCP (email vem do token, não declarado).
   REST só para automações internas (n8n), com API key rotacionada via env.
2. Cada usuário opera com o **próprio token Google** — Google é a 1ª camada
   de acesso; o filtro por área no Postgres é a 2ª (defesa em profundidade).
3. **Fail-closed**: notebook sem classificação de área é invisível para
   juridico/financeiro (admin/gestor veem tudo).
4. Níveis: `admin` · `gestor` · `juridico` · `financeiro`. Financeiro é nível **paralelo**, não
   inferior: o gate das tools passa a ser "cadastrado e ativo" + filtro por
   área (corrige a trava atual que bloqueia financeiro de tudo).
5. Toda pergunta gravada em `audit_log`.

## Tools do produto final (12 MCP)

| # | Tool | Nível | Fase |
|---|---|---|---|
| 1 | `quem_sou_eu` | logado | ✅ entregue |
| 2 | `verificar_token` | logado | ✅ entregue |
| 3 | `listar_notebooks` | cadastrado (filtro por área) | ✅ entregue |
| 4 | `perguntar` | cadastrado (filtro por área) | ✅ entregue |
| 5 | `listar_fontes` | cadastrado (filtro por área) | ✅ entregue |
| 6 | `criar_notebook` | admin | F2 |
| 7 | `adicionar_fonte` (URL e Drive) | gestor | F2 |
| 8 | `gerar_relatorio` | juridico/financeiro (área) | F3 |
| 9 | `gerar_podcast` | juridico/financeiro (área) | F3 |
| 10 | `baixar_artefato` | mesmo nível do gerar | F3 |
| 11 | `compartilhar_notebook` (por área) | admin | F4 |
| 12 | `historico` (auditoria de conversas) | gestor | F4 |

REST espelha 6–12 para o n8n. Nada além dessas 12 — comandos restantes da
lib (notas, quiz, flashcards, vídeos, research, persona) ficam **fora do
escopo** v1.0.

## Fases de entrega

- **F1 — Fundação (✅ entregue):** servidor MCP+REST, OAuth, tokens Fernet,
  5 tools, níveis, audit, fail-closed, hardening (deps com hash, Python 3.13,
  chave rotacionada).
- **F2 — Gestão de conteúdo:** tools 6–7 + correção do gate do financeiro +
  classificação dos 277 notebooks na tabela `notebooks` (script + revisão humana).
- **F3 — Artefatos:** tools 8–10 (relatório e podcast por notebook, com
  download). É a entrega de maior valor percebido pelo cliente.
- **F4 — Governança:** tools 11–12, cron de refresh de tokens na máquina do
  escritório, onboarding das contas Google reais (descomissionar tokens de
  desenvolvimento), classificação automática de notebooks novos por prefixo
  (`CONT -` → juridico etc.).

## Critérios de aceite do produto final

1. O Doutor pergunta sobre qualquer caso pelo Claude e recebe resposta com citações.
2. Financeiro consulta apenas notebooks financeiros; jurídico apenas jurídico/processos — verificado com contas reais.
3. Gestor adiciona fonte (decisão, PDF via Drive) a um caso pelo Claude.
4. Relatório e podcast de um caso gerados e baixados pelo Claude.
5. Auditoria: gestor lista quem perguntou o quê na semana.
6. Tokens não expiram em operação normal (cron ativo) e nenhum segredo vive em código/docs.

## Fora do escopo (explícito)

- Interface própria (web/app) — o front é o Claude.
- Upload de arquivo local pela REST (limite da lib; Drive cobre o caso).
- Notebooks de outras contas/escritórios; multi-tenancy.
- Garantia de SLA do NotebookLM (lib não-oficial; risco aceito e documentado).

## Pendências operacionais (pré-F2)

2. Decidir máquina-host dos perfis/cron (recomendado: máquina da organização).
3. Conta Google definitiva do Doutor conectada como admin.
