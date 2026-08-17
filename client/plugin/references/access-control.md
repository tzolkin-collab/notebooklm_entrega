# Controle de Acesso

## Níveis

Quatro níveis. `juridico` e `financeiro` são **paralelos**, não hierárquicos —
nenhum contém o outro; cada um enxerga os notebooks classificados para a sua
área.

| Nível | Alcance |
|---|---|
| `admin` | tudo, incluindo criação de notebooks e gestão de usuários |
| `gestor` | tudo em leitura, mais gestão de conteúdo (adicionar fontes) |
| `juridico` | notebooks classificados como jurídico e processos |
| `financeiro` | notebooks classificados como financeiro |

A relação entre pessoas e níveis vive na tabela `notebooklm.users` do banco, não
em arquivo. Um admin define o nível de cada pessoa via `POST /api/admin/users`.

## Permissões

| Ação | admin | gestor | juridico | financeiro |
|---|---|---|---|---|
| `/notebook ask` (jurídico) | ✅ | ✅ | ✅ | ❌ |
| `/notebook ask` (financeiro) | ✅ | ✅ | ❌ | ✅ |
| `/notebook list` | ✅ | ✅ | ✅ (filtrado) | ✅ (filtrado) |
| `/notebook use` | ✅ | ✅ | ✅ (filtrado) | ✅ (filtrado) |
| `/notebook sources` | ✅ | ✅ | ✅ | ✅ |
| `/notebook add-source` | ✅ | ✅ | ❌ | ❌ |
| `/notebook create` | ✅ | ❌ | ❌ | ❌ |
| `/notebook auth` | ✅ | ✅ | ✅ | ✅ |
| `/notebook refresh` | ✅ | ✅ | ✅ | ✅ |
| `/notebook team` | ✅ | ❌ | ❌ | ❌ |
| `/notebook register` | ✅ | ❌ | ❌ | ❌ |

## Notebooks por área

| Área | Níveis com acesso |
|---|---|
| Jurídico | admin, gestor, juridico |
| Processos | admin, gestor, juridico |
| Financeiro | admin, gestor, financeiro |
| Estratégico | admin, gestor |

A classificação de cada notebook fica na tabela `notebooklm.notebooks`. Notebook
sem classificação é **invisível** para `juridico` e `financeiro` — fail-closed.
Só `admin` e `gestor` enxergam o não-classificado.

## Como o usuário é identificado

A identidade é **autenticada pelo servidor**, nunca declarada na conversa:

- **Conector MCP (Claude):** OAuth Google — o email vem do token assinado.
- **API REST:** token Bearer por usuário — email e nível vêm do token no banco.

Não conceda acesso com base em email informado por texto. O servidor aplica o
nível a partir da credencial autenticada. Em caso de dúvida, nível mais
restritivo.
