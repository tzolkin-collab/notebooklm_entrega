# Guia do Doutor

Doutor, este é o documento para **usar e administrar** o sistema no escritório.
Sem termos técnicos.

> Se você é da equipe que vai **instalar**, este não é o seu documento — o seu é
> o `HANDOFF.md`, e depois o `DEPLOY.md`.

---

## Em uma frase

O Doutor pergunta ao Claude sobre qualquer caso do escritório, e ele responde
consultando os notebooks do NotebookLM, **citando de onde tirou** — respeitando
quem no escritório pode ver o quê.

---

## Antes de tudo: hoje ele não está no ar

Isto é o mais importante deste documento.

O que foi entregue é o **programa**, não o serviço funcionando. Ele vem
deliberadamente **sem nenhuma senha, chave ou login** — nem a chave que
protege os dados, nem a senha do banco, nem o cadastro do Google.

Isso não é esquecimento. Uma chave que passa de uma empresa para outra deixa de
proteger aquilo que ela deveria proteger. Quem assume o projeto gera as próprias,
e a partir daí ninguém de fora tem acesso ao acervo do escritório — nem nós.

**O servidor do escritório já existe.** Não é preciso contratar nada novo. O que
falta é publicar esta versão nele e criar as chaves de acesso.

A consequência prática é a ordem das coisas:

| | O quê | Quem faz |
|---|---|---|
| 1 | Publicar esta versão no servidor que já existe, e criar as chaves | a nova consultoria |
| 2 | Fazer o primeiro login, uma vez por pessoa | o Doutor e a equipe |
| 3 | Classificar os notebooks por área | a nova consultoria, com revisão do Doutor |
| 4 | Usar | o Doutor e a equipe |

**Enquanto o passo 1 não acontecer, nada do que está abaixo funciona.** Não
adianta abrir o Claude e procurar — não vai estar lá.

---

## O que dá para fazer

Depois de instalado, dentro do Claude, em conversa normal:

| O que pedir | O que acontece |
|---|---|
| "Quais notebooks eu tenho?" | lista os que o nível permite ver |
| "O que o notebook X diz sobre prescrição?" | responde **citando a fonte** |
| "Quais são as fontes do notebook X?" | lista os documentos daquele notebook |
| "Cria um notebook chamado Y" | cria (só quem é admin) |
| "Adiciona este link ao notebook X" | adiciona por link ou Google Drive |
| "Compartilha o notebook X com fulano" | compartilha, e dá para conferir com quem está |

Não é um site nem um aplicativo à parte. **A tela é o próprio Claude.** Foi
decisão de escopo desde o início: interface própria ficou de fora.

---

## O que NÃO foi construído

Estava previsto e não foi entregue. O Doutor precisa saber disto antes de
combinar prazo com a nova consultoria:

**Relatório e podcast gerados pelo Claude.** Estava previsto na fase 3 do escopo
e **não foi construído** — conferido no código, arquivo por arquivo.

**Consultar a auditoria pelo Claude.** Toda pergunta feita ao sistema **é**
registrada, com autor, data e conteúdo. O que não existe é o jeito de ler esse
registro conversando com o Claude — hoje só se consulta direto no banco, com
ajuda técnica.

**Renovação automática do login do Google.** O login de cada pessoa expira de
tempos em tempos. Estava previsto um mecanismo que renovasse sozinho; ele não
foi construído. Na prática, alguém vai refazer o login (o passo 2 abaixo) de
vez em quando. Vale pedir à nova consultoria que faça isso cedo — é a diferença
entre o sistema funcionar e funcionar sem ninguém precisar pensar nele.

---

## Passo a passo 1 — ligar o Claude ao sistema

Uma vez, em cada computador.

1. No Claude, abra **Configurações → Conectores**
2. **Adicionar conector personalizado**
3. Cole o endereço que a consultoria vai passar, terminando em `/mcp`
4. **Vincular** → **Continuar com Google**, com a conta do escritório

Pronto. A partir daí é só conversar.

O Claude sabe quem é o Doutor pelo login do Google — não há senha separada para
decorar, e não há como alguém se passar por ele.

---

## Passo a passo 2 — dar acesso a alguém da equipe

São três movimentos, e **a ordem importa**.

### 2.1 — O Doutor convida

Abra o **painel de administração** (como abrir está mais abaixo) e clique em
**Convidar pessoa**. Informe o email dela.

O painel devolve um código. Pode mandar por WhatsApp ou email interno sem
preocupação: ele serve para **aquele email**, **uma vez só**, expira sozinho, e
**não dá acesso a nada** por si — quem usa entra parado, esperando liberação.

### 2.2 — A pessoa faz o login dela

Numa máquina do escritório preparada para isso, ela dá **duplo clique em
`Conectar ao NotebookLM.bat`**, preenche o email, o nome e o código, e clica em
Conectar.

Abre uma janela do Google. Ela entra com a conta dela — a mesma que usa no
NotebookLM. Uns 5 minutos.

> **Basta uma máquina para o escritório inteiro.** O cadastro é da pessoa, não do
> computador. Cada um senta, faz o login, e pronto. Não precisa instalar nada no
> computador de cada advogado.

### 2.3 — O Doutor libera e escolhe o nível

De volta ao painel, a pessoa aparece como **pendente**. Clique em **Alterar
acesso**, escolha o nível, confirme.

Ela entra parada de propósito: assim ninguém se promove sozinho fazendo o
próprio cadastro. Quem decide o nível é o Doutor.

---

## Passo a passo 3 — tirar acesso

No painel, **Revogar acesso**. Vale para quando alguém sai do escritório ou muda
de função.

Revogar apaga a credencial da pessoa — ela deixa de existir, não só de
funcionar. Se reativar depois, é uma credencial nova.

> Quando alguém **sai do escritório**, revogar aqui é necessário mas não basta:
> o login do Google dela continua guardado no sistema até ser apagado. Peça à
> equipe técnica para remover — é rápido, mas alguém precisa pedir.

---

## Os níveis

| Nível | Vê | Pode |
|---|---|---|
| **admin** | tudo | criar notebooks, gerir a equipe |
| **gestor** | tudo | adicionar fontes |
| **jurídico** | notebooks de jurídico e processos | consultar |
| **financeiro** | notebooks de financeiro | consultar |

Jurídico e financeiro são **lado a lado**, não um acima do outro. Quem é do
financeiro não é "um jurídico com menos permissão" — é outra área, e não enxerga
a do outro.

---

## Como abrir o painel de administração

Duplo clique em **`Administrar Acessos.bat`**.

O computador precisa ter o Python instalado — é gratuito, vem de
[python.org/downloads](https://python.org/downloads), e na instalação é preciso
marcar a opção **"Add Python to PATH"**. É uma máquina só, e uma vez só. Se
faltar algo, o próprio programa avisa e oferece instalar.

Na **primeira vez** ele pede três coisas: o endereço do servidor, a chave de
administrador (a consultoria entrega) e **uma senha que o Doutor cria**. A chave
fica guardada embaralhada com essa senha. **Depois disso, só a senha.**

Existe também um `Administrar Acessos.exe`, que faz o mesmo sem precisar de
Python. Mas o Windows exibe um aviso — *"O Windows protegeu o seu PC"* — porque
o programa não tem assinatura digital, que é um certificado pago. Dá para passar
pelo aviso, mas **prefira o `.bat`**: ele abre limpo, e não vale acostumar
ninguém a clicar em "executar assim mesmo" num sistema que guarda material sob
sigilo.

### Se preferir levar no pendrive

Há a opção de guardar a chave **no próprio pendrive**, em vez de no computador.
Aí valem duas coisas ao mesmo tempo: o pendrive que o Doutor tem em mãos e a
senha que só ele sabe.

Com o pendrive fora, aquele computador fica **sem credencial nenhuma**. E se o
pendrive se perder, quem achar tem um arquivo embaralhado, inútil sem a senha.

---

## Quando parecer quebrado

| O que aparece | O que é | O que fazer |
|---|---|---|
| **A equipe abre e a lista vem vazia** | os notebooks ainda não foram classificados por área | pedir a classificação à consultoria — é o passo 3 lá do começo |
| "Usuário não cadastrado ou inativo" | faltou liberar no painel, ou o acesso foi revogado | liberar no painel |
| Uma mensagem pedindo para rodar o Conector | a pessoa foi liberada mas nunca fez o login do Google | refazer o passo 2.2 |
| Listava e agora perguntar falha | o login do Google daquela pessoa expirou | refazer o passo 2.2 |
| O código de convite não funciona | já foi usado, expirou, ou é de outro email | gerar outro no painel |

A primeira linha é a que mais gera susto: **num sistema recém-instalado, todo
mundo vê lista vazia.** Não é defeito. É proposital — um notebook que ninguém
classificou não aparece para ninguém, porque errar para o lado de esconder é
melhor do que errar para o lado de mostrar.

---

## Cuidados que o sigilo profissional exige

**Cada pessoa com a conta dela.** O sistema registra quem perguntou o quê. Conta
compartilhada destrói exatamente isso — e é o registro que permite responder,
um dia, "quem acessou este caso".

**As perguntas e respostas ficam gravadas.** Embaralhadas, mas com a chave do
servidor. Quem administra o servidor consegue ler consultas sobre casos dos
clientes do escritório. Isso é material sob sigilo: quem tem acesso ao servidor
precisa ser tratado com o mesmo critério de quem tem acesso ao arquivo físico.

**O sistema é fonte, não delegação de responsabilidade.** Ele responde citando
de onde tirou. A citação existe para ser conferida.

---

## Um risco que o Doutor deveria conhecer

O sistema conversa com o NotebookLM por uma biblioteca **não oficial** — não
feita pelo Google. Não há compromisso de compatibilidade: o Google pode mudar
algo do lado dele e o conector parar de funcionar sem aviso.

O risco foi aceito e registrado desde o escopo inicial, porque não existe hoje um
caminho oficial. Vale saber que, se um dia parar do nada, provavelmente é isso —
e é conserto de dias, não de meses.

---

## Onde está cada coisa

| Documento | Para quem |
|---|---|
| **este** | o Doutor |
| `ACESSOS.md` | quem administra acessos no dia a dia, com mais detalhe |
| `GUIA-DA-CONSULTORIA.md` | a nova consultoria — por onde ela deve começar |
| `HANDOFF.md` | a nova consultoria, para entender o que recebeu |
| `DEPLOY.md` | a nova consultoria, para instalar |
| `ESCOPO.md` | o que foi combinado no início, para comparar com o entregue |
