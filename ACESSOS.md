# Gestão de acessos

Como conceder, revogar e manter o acesso das pessoas ao conector.

Este documento é para **quem administra o dia a dia** — não para quem instala.
Instalação está no `DEPLOY.md`; contexto do projeto, no `HANDOFF.md`.

---

## Quem faz o quê

| Papel | Responsabilidade |
|---|---|
| **Equipe técnica** | instala o servidor, o banco e o cliente OAuth. Emite o token do primeiro admin. Depois disso, sai do caminho. |
| **Admin da organização** | concede e revoga acesso, define níveis. Não precisa de acesso ao servidor nem ao banco. |
| **Cada pessoa** | faz o próprio login Google, uma vez. |

A separação é proposital: conceder acesso **não exige** tocar em infraestrutura.
Depois do primeiro admin existir, tudo se resolve por chamadas à API.

---

## Conceder acesso a alguém — 3 passos

### Passo 1 — o admin emite um token de onboarding

```bash
curl -X POST -H "Authorization: Bearer <token-admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@dominio.com","ttl_horas":48}' \
  <PUBLIC_URL>/api/admin/onboarding-token
```

A resposta traz o token. Ele é **de uso único**, **ligado àquele email** e
**expira** no prazo dado.

### Passo 2 — a pessoa faz o login

Na máquina de onboarding, **duplo clique em `Conectar ao NotebookLM.bat`**.

Abre uma janela pedindo email, nome e o código de acesso do passo 1. A pessoa
preenche, clica em *Conectar*, e o resto acontece sozinho.

Na primeira vez naquele computador, o app avisa que faltam componentes (~150 MB)
e instala sob confirmação. Uma vez só.

> Pela linha de comando, se preferir:
> ```bash
> set NOTEBOOKLM_SERVER_URL=<PUBLIC_URL>
> set NOTEBOOKLM_ONBOARDING_TOKEN=<token recebido>
> python connect.py --email pessoa@dominio.com --nome "Nome Completo"
> ```
> A janela é só um invólucro — chama esse mesmo script.

Abre uma janela do Chromium. A pessoa entra com a conta Google dela — a mesma
que usa no NotebookLM. O script envia a sessão ao servidor, que cifra e guarda, e
**apaga o perfil local em seguida**.

O cadastro entra **pendente**: existe, mas inativo, sem nível útil.

### Passo 3 — o admin ativa e define o nível

```bash
curl -X POST -H "Authorization: Bearer <token-admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@dominio.com","nivel":"juridico","ativo":true}' \
  <PUBLIC_URL>/api/admin/users
```

A resposta traz o `api_token` Bearer da pessoa — necessário só se ela for usar a
API REST. Para usar pelo Claude, não precisa: lá a identidade vem do login Google.

---

## Como entregar o token de onboarding

Ele pode ir por canal comum — WhatsApp, email interno. O risco é baixo **por
desenho**, não por descuido:

- serve para **um** email; em outro, é recusado
- serve **uma vez**; a segunda tentativa falha
- expira sozinho
- **não concede privilégio** — quem o usa entra inativo, e a ativação é decisão do admin

O que um token vazado permite, no pior caso: alguém que já controle a conta Google
daquela pessoa enviar a sessão dela. Que é exatamente o que a pessoa faria.

O que **não** pode circular por canal comum é o `api_token` (`nlm_...`), que é
credencial de verdade e dá acesso imediato no nível da pessoa.

---

## Os níveis

| Nível | Enxerga | Pode |
|---|---|---|
| `admin` | tudo | criar notebooks, gerir usuários, ver auditoria |
| `gestor` | tudo | adicionar fontes |
| `juridico` | notebooks de jurídico e processos | consultar |
| `financeiro` | notebooks de financeiro | consultar |

`juridico` e `financeiro` são **paralelos**, não uma hierarquia — nenhum contém o
outro. Alguém do financeiro não é "um jurídico com menos permissão"; é outra área.

### O que cada um vê depende da classificação dos notebooks

Notebook sem área classificada é **invisível** para `juridico` e `financeiro`. Só
`admin` e `gestor` enxergam o não-classificado.

É proposital — inconveniência no lugar de vazamento. Mas tem uma consequência que
gera chamado: **num ambiente recém-instalado, todo mundo vê lista vazia** até
`scripts/classifica_notebooks.py` rodar. Não é falha.

---

## Revogar acesso

```bash
curl -X POST -H "Authorization: Bearer <token-admin>" -H "Content-Type: application/json" \
  -d '{"email":"pessoa@dominio.com","nivel":"juridico","ativo":false}' \
  <PUBLIC_URL>/api/admin/users
```

Desativar **apaga o `api_token`** na mesma operação — a credencial deixa de
existir, não só de funcionar. Reativar depois não ressuscita o token antigo: um
novo é emitido.

> Quando alguém sai da organização, desativar aqui é necessário mas não
> suficiente: a sessão Google guardada continua no banco até ser sobrescrita.
> Peça à equipe técnica para remover a linha em `notebooklm.tokens`.

---

## O painel de administração

**Duplo clique em `Administrar Acessos.bat`.**

Precisa de Python na máquina — [python.org/downloads](https://python.org/downloads),
marcando *Add Python to PATH* na instalação. É uma máquina só, então o custo se
paga uma vez. Na primeira abertura o próprio `.bat` confere o que falta e oferece
instalar.

**Na primeira vez**, ele pede o endereço do servidor, a sua chave de
administrador e uma senha que você cria. A chave fica guardada **cifrada** com
essa senha. **Depois disso, só a senha.**

No endereço, use só a base — sem `/mcp` nem `/api` no final. (Ele tolera as duas
formas, mas vale saber qual é qual.)

A janela mostra a equipe com a situação de cada pessoa:

| Situação | Significa |
|---|---|
| `ativo` | usando normalmente |
| `pendente` | enviou a sessão Google, **aguardando você liberar** |
| `ativo, sem sessao` | liberado, mas ainda não rodou o Conector — vai receber erro |
| `inativo` | sem acesso |

Quatro botões cobrem a rotina: **Convidar pessoa**, **Alterar acesso**,
**Revogar acesso**, **Atualizar**.

### E o `Administrar Acessos.exe`?

Faz exatamente o mesmo e dispensa Python. Mas o Windows **barra** ele —
*"O Windows protegeu o seu PC"* — por ser um executável **sem assinatura
digital**. Dá para passar em *Mais informações → Executar assim mesmo*, uma vez
por máquina.

Não é defeito do programa: é o SmartScreen fazendo o trabalho dele, e o aviso
some com um certificado de assinatura de código (anuidade, exige CNPJ) — decisão
comercial, não técnica. Enquanto não houver certificado, prefira o `.bat`: ele
chama o `python.exe`, que **é** assinado, e abre sem aviso nenhum.

Evite acostumar quem usa a clicar em "executar assim mesmo". Num sistema que
existe para proteger material sob sigilo, esse é o hábito errado de ensinar.

### No pendrive, se preferir

Há a opção **"Guardar ao lado deste programa (pendrive)"** na tela de registro.

Copie **para o pendrive antes** de registrar — a pasta `client/` inteira se for
usar o `.bat`, ou só o arquivo se for o `.exe`. O cofre nasce ao lado do
programa: se o programa estiver noutro lugar, é lá que ele fica.

| | |
|---|---|
| Pendrive plugado | entra com a senha |
| Pendrive removido | a máquina fica **sem credencial nenhuma** |
| Pendrive perdido | quem achar tem um arquivo cifrado, inútil sem a senha |

Dois fatores de verdade: o pendrive que você tem e a senha que você sabe.

Uma ressalva sobre "em qualquer computador": pelo `.bat`, o computador precisa ter
Python. O `.exe` roda em qualquer um, mas encara o SmartScreen em cada máquina
nova. Se a ideia é circular por máquinas emprestadas, o `.exe` é o que de fato
funciona — ao preço daquele aviso.

> Se o programa estiver dentro de uma pasta versionada (git), o app avisa antes
> de gravar. O cofre ali poderia acabar enviado junto com o código.

### O que a senha protege

Ela não vai para o servidor — não há login remoto. Abre um cofre local onde a
chave está cifrada.

**Protege** de quem copiar o arquivo: sem a senha, o conteúdo é inútil.

**Não protege** de quem controla o computador com o painel aberto — aí a chave
está em memória. Nenhum cofre local resolve isso.

*Esquecer este computador* apaga o cofre. Isso **não revoga** o acesso; revogar
se faz no servidor.

---

## A máquina de onboarding

O login precisa de Python e de um Chromium do Playwright (~150 MB). Instalar isso
no computador de cada advogado é fricção desnecessária — e não é preciso.

Prepare **uma** máquina: copie a pasta `client/` para ela e deixe um atalho de
`Conectar ao NotebookLM.bat` na área de trabalho. A partir daí é duplo clique.

**Nada amarra o perfil a um computador.** A sessão é da pessoa; a máquina é
descartável. Uma máquina só, do escritório, resolve: cada pessoa senta, roda o
comando com o próprio email, faz login, e o token sobe. Uns 5 minutos por pessoa.

O `connect.py` apaga o perfil local depois de enviar. Se ele avisar que **não
conseguiu apagar**, apague à mão:

```
%USERPROFILE%\.notebooklm\profiles\<perfil>
```

Isso importa: aquele arquivo são os cookies da conta Google da pessoa, em texto
claro, e dão acesso à **conta inteira** — não só ao NotebookLM. Numa máquina
compartilhada eles se acumulariam, uma pessoa por perfil, tornando aquele
computador mais sensível que o próprio servidor, que ao menos cifra.

---

## Quando parar de funcionar

| Sintoma | Causa | O que fazer |
|---|---|---|
| `Usuario X nao cadastrado ou inativo` | passo 3 não foi feito, ou o acesso foi revogado | admin ativa |
| Lista de notebooks vazia | notebooks sem classificação de área | rodar `classifica_notebooks.py` |
| `409` com `"acao"` dizendo para rodar o `connect.py` | pessoa ativada sem ter enviado a sessão Google, ou sessão removida | refazer o passo 2 |
| Lista funciona, mas perguntar falha | sessão Google expirou | `renovar_token`; se não resolver, refazer o passo 2 |
| `Erro 400: redirect_uri_mismatch` | `PUBLIC_URL` não bate com o registrado no Google Cloud | equipe técnica |
| `403` ao usar token de onboarding | já usado, expirado, ou email diferente | admin emite outro |

**A sessão Google expira** e não há renovação automática agendada — estava
prevista no escopo e não foi construída. Na prática, alguém vai refazer o passo 2
de tempos em tempos. Montar esse agendamento cedo é a diferença entre o sistema
funcionar e funcionar sem ninguém pensar nisso.

---

## O que não fazer

**Não compartilhar conta.** Cada pessoa com a sua. O `audit_log` registra quem
perguntou o quê — conta compartilhada destrói a rastreabilidade, que num contexto
de sigilo profissional é o que permite responder "quem acessou este caso".

**Não rodar as ferramentas de `server/db/` em máquina de usuário.** Elas exigem a
chave de criptografia e o acesso ao banco. São break-glass de administrador.

**Não reaproveitar o `api_token` de uma pessoa em automações.** Se o n8n precisa
acessar, crie um usuário próprio para ele, com o nível mínimo. Assim revogar o
acesso de uma pessoa não derruba a automação, e vice-versa.
