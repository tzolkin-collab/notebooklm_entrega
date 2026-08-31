# NotebookLM — aplicativos de acesso

Dois programas de janela para o dia a dia do conector NotebookLM:

| Programa | Para quem | O que faz |
|---|---|---|
| **Conectar ao NotebookLM** | cada pessoa da equipe, uma vez | login Google e envio da sessão ao servidor |
| **Administrar Acessos** | quem administra | convida, libera, muda nível e revoga acesso |

Nenhum dos dois guarda chave de banco, nem a chave de criptografia do servidor.
Os dois falam com a API por HTTPS.

---

## Instalação

Só é preciso **Python 3.10 ou mais novo**, com a opção *Add Python to PATH*
marcada durante a instalação. Baixe em <https://python.org/downloads>.

Copie a pasta inteira para o computador e dê duplo clique no `.bat` desejado.
Na primeira execução cada programa instala o que falta e avisa antes.

---

## Conectar ao NotebookLM (onboarding)

Feito **uma vez por pessoa**. É o que dá ao servidor a autorização para
consultar o NotebookLM em nome dela.

1. Peça um **código de acesso** a quem administra.
2. Duplo clique em `Conectar ao NotebookLM.bat`.
3. Preencha email Google, nome e o código.
4. Clique em **Conectar**. Abre um navegador para o login Google.
5. Ao terminar, o cadastro fica **pendente** — alguém precisa liberar.

Na primeira execução são baixados cerca de 150 MB (o navegador usado no login).
A janela pergunta antes.

> O código de acesso vale **uma vez só**, está preso ao email para o qual foi
> emitido e **não concede privilégio nenhum** por si: quem o usa entra inativo.
> Liberar continua sendo decisão de quem administra. Por isso ele pode ser
> enviado por email ou mensagem comum.

Depois do envio, os cookies da sessão Google são **apagados do computador**.
Se o programa não conseguir apagá-los, ele avisa em letras garrafais — nesse
caso apague à mão a pasta indicada.

### Pela linha de comando

```
set NOTEBOOKLM_ONBOARDING_TOKEN=<código>
python setup.py
```

`setup.py` instala as dependências e chama `connect.py`. Para apontar a outro
servidor, defina `NOTEBOOKLM_SERVER_URL` antes.

---

## Administrar Acessos (painel)

Duplo clique em `Administrar Acessos.bat`.

### Primeira vez neste computador

Cole sua **chave de administrador** (começa com `nlm_`) e crie uma senha. A
chave passa a ficar guardada cifrada; das próximas vezes basta a senha.

> A senha protege uma chave com acesso administrativo ao acervo. Use no mínimo
> 8 caracteres — e não a reaproveite de outro lugar.

### Onde a chave fica

Você escolhe na hora do registro. Qualquer pasta serve; o painel lista as opções:

| Opção | Quando |
|---|---|
| **Pendrive** *(recomendado)* | a chave anda com você e não fica na máquina |
| Neste computador | um computador só, sempre o mesmo |
| Outra pasta | qualquer caminho, escolhido numa janela |

Os pendrives aparecem na lista **automaticamente**, pelo tipo da unidade — não
por uma letra guardada em configuração. Isso importa: `E:` num computador pode
ser `F:` no outro, ou mudar só de trocar a porta USB. Como a busca pergunta ao
sistema quais unidades são removíveis, funciona em qualquer porta e em qualquer
máquina, sem nada para configurar.

Plugue o pendrive **antes** de abrir o painel, para ele aparecer na lista.

Na hora de entrar, a ordem de procura é: pendrive plugado, depois a pasta do
programa, depois este computador.

> **Ter duas chaves anula o sentido de carregar uma.** Se houver uma no pendrive
> e outra neste computador, tirar o pendrive não tira o acesso daqui — são duas
> credenciais que funcionam sozinhas. Quando isso acontece o painel avisa na
> tela de entrada e oferece apagar a deste computador.

### Trocar por uma chave nova

Vem marcado. A chave que você cola na primeira vez chegou por algum canal —
email, mensagem, um papel — e continua existindo lá depois de usada.

Com a opção marcada, o painel guarda a chave colada, pede ao servidor uma
substituta e sela **essa** no cofre. A colada deixa de funcionar na hora, e a
cópia que ficou no canal por onde ela veio vira um texto inútil.

**Desmarque** se essa mesma chave estiver em uso numa automação (n8n ou
similar): trocá-la aqui derrubaria a integração.

### A ordem das coisas

```
1. Convidar pessoa  ──►  2. Ela faz o login dela  ──►  3. Você libera e dá o nível
      (código)                (Conectar ao NotebookLM)          (Alterar acesso)
```

Liberar antes do login deixa a pessoa cadastrada sem sessão, e ela recebe erro
ao perguntar. Espere ela aparecer na lista como **pendente**.

### A coluna "situação"

| Situação | Significa |
|---|---|
| `pendente` | fez o login, aguarda liberação |
| `ativo` | tudo certo |
| `ativo, sem sessao` | liberado, mas o login Google não foi feito ou expirou |
| `inativo` | acesso revogado ou ainda não liberado |

### Níveis

| Nível | Alcance |
|---|---|
| `admin` | tudo, inclusive gerir usuários |
| `gestor` | tudo em leitura, mais adicionar fontes |
| `juridico` | notebooks de jurídico e processos |
| `financeiro` | notebooks de financeiro |

Jurídico e financeiro são áreas paralelas: nenhuma contém a outra.

### A chave de API

Ao liberar acesso, o servidor emite uma chave de API nova para a pessoa e a
anterior para de funcionar. O painel mostra a nova numa janela com botão de
copiar — é a única vez que ela aparece.

Ela serve **só** para integrações que falam direto com a API (n8n e afins).
Quem consulta o acervo pelo Claude não precisa dela e pode fechar a janela.

### Revogar

Desliga o acesso na hora e apaga o token de API da pessoa. A **sessão Google
guardada continua no banco** até ser sobrescrita — se a pessoa saiu da
organização, peça à equipe técnica para removê-la de vez.

### Esquecer este computador

Apaga só o cofre local. **Não revoga acesso nenhum** — isso se faz no servidor.

---

## Endereço do servidor

Vem embutido em `admin.pyw`, `app.pyw` e `connect.py`, na constante
`SERVIDOR_PADRAO`. Para apontar a outro ambiente, use a variável de ambiente
`NOTEBOOKLM_SERVER_URL`, ou deixe a constante vazia — aí o campo reaparece na
janela.

Se o servidor mudar de host, o mesmo valor precisa ser trocado em
`plugin/plugin.json`, `plugin/SKILL.md` e `plugin/references/commands.md`, e o
`.skill` reempacotado. Ele também tem que bater com o `redirect_uri` registrado
no Google Cloud Console — se divergir, o sintoma é `Erro 400: redirect_uri_mismatch`.

---

## O executável

`build_exe.py` gera `Administrar Acessos.exe`, que roda em máquina **sem
Python** — útil para um pendrive que circula.

```
pip install pyinstaller
python build_exe.py
```

O executável **não é assinado digitalmente**, então o Windows mostra "O Windows
protegeu o seu PC" na primeira execução. Não é vírus nem detecção: é falta de
reputação, e só um certificado de assinatura de código resolve de verdade. É por
isso que o `.bat` é o caminho principal — ele chama o `python.exe`, que já vem
assinado, e não gera aviso.

O conector de onboarding não é empacotado: ele depende de um navegador de
~150 MB que seria baixado na primeira execução de qualquer forma.

---

## Arquivos

```
Conectar ao NotebookLM.bat   abre o onboarding
Administrar Acessos.bat      abre o painel
app.pyw                      janela do onboarding
admin.pyw                    janela do painel
connect.py                   login Google e envio da sessão
cofre.py                     guarda a chave de administrador cifrada
setup.py                     instalação pela linha de comando
build_exe.py                 gera o executável do painel
requirements.txt             dependências do onboarding
plugin/                      skill e referências do conector no Claude
```

`requirements.txt` cobre o **onboarding**. O painel precisa apenas de
`cryptography`, e o `.bat` dele instala só isso.

---

## Quando algo não funciona

| Sintoma | Causa provável |
|---|---|
| duplo clique e nada acontece | Python fora do PATH — reinstale marcando *Add Python to PATH* |
| "Token de administrador inválido" | chave errada ou desativada |
| "Este token não tem nível de administrador" | a chave é de usuário comum |
| "Endereço do servidor não confere" | use só o endereço base, sem `/mcp` nem `/api` |
| `Erro 400: redirect_uri_mismatch` | endereço do servidor ≠ `redirect_uri` no Google Cloud Console |
| pessoa some da lista | ela ainda não fez o login do passo 2 |
