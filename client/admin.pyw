# -*- coding: utf-8 -*-
"""
Painel de administracao do conector NotebookLM.

Substitui os comandos `curl` do ACESSOS.md por uma janela: convidar alguem,
ativar, mudar nivel, revogar. Quem administra o acervo de um escritorio nao
deveria precisar montar requisicao HTTP a mao para liberar o acesso de uma
pessoa nova.

Fala com a API REST, nao com o banco. Isso importa por tres motivos: usa o mesmo
caminho ja testado, respeita o gate de nivel do servidor (o painel nao pode dar
mais acesso do que o token de quem o abriu), e nao exige a chave Fernet nem a
DATABASE_URL na maquina de quem administra.

Extensao .pyw: abre sem console atras. Fora da biblioteca padrao, so depende de
`cryptography`, usada pelo cofre local (cofre.py).
"""
import json
import os
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import messagebox, ttk

try:
    import cofre
except ImportError as erro:
    # Sem console, um ImportError aqui e invisivel: o .pyw roda sob pythonw, o
    # traceback vai para um stderr que o `start ""` do .bat descarta, e a pessoa
    # ve a janela simplesmente nao abrir. Sem mensagem, sem codigo de erro, sem
    # pista. Verificado: pythonw sai com codigo 1 e nada aparece na tela.
    #
    # A caixa de dialogo abaixo e a unica forma de a falha chegar a quem clicou.
    _raiz = tk.Tk()
    _raiz.withdraw()
    messagebox.showerror(
        "Falta um componente",
        "O painel precisa da biblioteca 'cryptography' para guardar sua chave "
        "de administrador cifrada.\n\n"
        "Abra o Prompt de Comando e rode:\n\n"
        "    python -m pip install --user cryptography\n\n"
        f"Detalhe tecnico: {erro}",
    )
    raise SystemExit(1)

# Preencher no empacotamento, junto com o <PUBLIC_URL> do plugin.json e do
# SKILL.md. Vazio, o campo aparece editavel na janela.
SERVIDOR_PADRAO = ""

NIVEIS = ["admin", "gestor", "juridico", "financeiro"]

COR_FUNDO = "#f4f4f2"
COR_OK = "#2f7d5d"
COR_ERRO = "#b03a2e"
COR_ATENCAO = "#a8791c"


def normalizar_servidor(url: str) -> str:
    """
    Aceita qualquer forma da URL que a pessoa tenha a mao.

    A URL que aparece em toda a documentacao termina em /mcp — e a do conector
    do Claude, a mais visivel. Colada aqui sem tratamento, o painel montaria
    .../mcp/api/team e receberia 404, com a pessoa sem ideia do porque.

    Tambem tolera /api no fim (quem copiou da secao REST) e barras sobrando.
    """
    u = url.strip().rstrip("/")
    for sufixo in ("/mcp", "/api"):
        if u.endswith(sufixo):
            u = u[: -len(sufixo)].rstrip("/")
    if u and not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


class Api:
    """Cliente HTTP minimo. Sem dependencia externa: urllib da stdlib basta."""

    def __init__(self, base: str, token: str):
        self.base = normalizar_servidor(base)
        self.token = token

    def _req(self, caminho: str, metodo: str = "GET", corpo: dict | None = None):
        r = urllib.request.Request(
            f"{self.base}/api{caminho}",
            method=metodo,
            data=json.dumps(corpo).encode("utf-8") if corpo else None,
        )
        r.add_header("Authorization", f"Bearer {self.token}")
        if corpo:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "replace")
            try:
                detalhe = json.loads(detalhe).get("detail", detalhe)
            except Exception:
                pass
            raise ErroApi(e.code, detalhe) from None
        except urllib.error.URLError as e:
            raise ErroApi(0, f"Nao consegui falar com o servidor: {e.reason}") from None

    def equipe(self):
        return self._req("/team")

    def convidar(self, email: str, horas: int):
        return self._req("/admin/onboarding-token", "POST",
                         {"email": email, "ttl_horas": horas})

    def definir_acesso(self, email: str, nivel: str, ativo: bool):
        return self._req("/admin/users", "POST",
                         {"email": email, "nivel": nivel, "ativo": ativo})


class ErroApi(Exception):
    def __init__(self, status: int, detalhe: str):
        self.status = status
        self.detalhe = detalhe
        super().__init__(detalhe)

    def amigavel(self) -> str:
        if self.status == 401:
            return ("Token de administrador invalido ou inativo.\n\n"
                    "Confira o token, ou peca um novo a quem tem acesso ao servidor.")
        if self.status == 403:
            return ("Este token nao tem nivel de administrador.\n\n"
                    f"Resposta do servidor: {self.detalhe}")
        if self.status == 404:
            return ("Endereco do servidor nao confere.\n\n"
                    "Use so o endereco base, sem /mcp e sem /api no final.\n"
                    "Exemplo: https://nome-do-servico.easypanel.host")
        if self.status == 429:
            return "Limite de requisicoes atingido. Aguarde um minuto."
        if self.status == 0:
            return self.detalhe
        return f"Erro {self.status}: {self.detalhe}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Administracao — NotebookLM")
        self.configure(bg=COR_FUNDO)
        self.api: Api | None = None
        self.fila: queue.Queue = queue.Queue()
        self._monta()
        self.after(100, self._drena)

    # ── interface ────────────────────────────────────────────────────────────
    def _monta(self):
        tk.Label(self, text="Administracao de acessos", bg=COR_FUNDO,
                 font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=4,
                                                     sticky="w", padx=16, pady=(16, 10))

        self.box = tk.Frame(self, bg=COR_FUNDO)
        self.box.grid(row=1, column=0, columnspan=4, sticky="we", padx=16)
        self._monta_acesso()

        cols = ("email", "nome", "nivel", "situacao")
        self.tabela = ttk.Treeview(self, columns=cols, show="headings", height=11)
        for c, t, w in [("email", "Email", 250), ("nome", "Nome", 160),
                        ("nivel", "Nivel", 100), ("situacao", "Situacao", 150)]:
            self.tabela.heading(c, text=t)
            self.tabela.column(c, width=w, anchor="w")
        self.tabela.grid(row=3, column=0, columnspan=4, padx=16, sticky="we")

        acoes = tk.Frame(self, bg=COR_FUNDO)
        acoes.grid(row=4, column=0, columnspan=4, sticky="we", padx=16, pady=10)
        self.botoes = []
        for txt, cmd in [("Convidar pessoa", self._convidar),
                         ("Alterar acesso", self._alterar),
                         ("Revogar acesso", self._revogar),
                         ("Atualizar", self._carregar_equipe)]:
            b = tk.Button(acoes, text=txt, command=cmd, font=("Segoe UI", 10),
                          relief="flat", bg="#e8e8e5", cursor="hand2",
                          padx=14, pady=6, state="disabled")
            b.pack(side="left", padx=(0, 8))
            self.botoes.append(b)

        self.status = tk.Label(self, text="Entre para administrar os acessos.",
                               bg=COR_FUNDO, fg="#5a5a56", font=("Segoe UI", 9))
        self.status.grid(row=5, column=0, columnspan=4, sticky="w", padx=16, pady=(0, 16))

    def _diz(self, txt, cor="#5a5a56"):
        self.status.configure(text=txt, fg=cor)

    def _habilita(self, ligado: bool):
        for b in self.botoes:
            b.configure(state="normal" if ligado else "disabled")

    # ── execucao em thread ───────────────────────────────────────────────────
    def _async(self, fn, ao_terminar):
        def alvo():
            try:
                self.fila.put((ao_terminar, fn(), None))
            except ErroApi as e:
                self.fila.put((ao_terminar, None, e))
            except Exception as e:                              # noqa: BLE001
                self.fila.put((ao_terminar, None, ErroApi(0, str(e))))
        threading.Thread(target=alvo, daemon=True).start()

    def _drena(self):
        # Sem esta guarda, o `after` continua reagendando depois que a janela
        # some e o Tk reclama de comando inexistente. Na pratica so aparece se
        # a janela for destruida com o processo vivo, mas o ruido confunde.
        if not self.winfo_exists():
            return
        try:
            while True:
                cb, resultado, erro = self.fila.get_nowait()
                if erro:
                    self._diz("Falhou.", COR_ERRO)
                    messagebox.showerror("Erro", erro.amigavel())
                else:
                    cb(resultado)
        except queue.Empty:
            pass
        self.after(100, self._drena)

    # ── acoes ────────────────────────────────────────────────────────────────
    def _monta_acesso(self):
        """
        Duas telas na mesma area: registro (primeira vez) e entrada (depois).

        Qual aparece depende so de o cofre existir. Nao ha escolha a fazer — se
        e a primeira vez, o unico caminho e registrar; se nao e, e entrar.
        """
        for w in self.box.winfo_children():
            w.destroy()

        primeira_vez = not cofre.existe()

        if primeira_vez:
            tk.Label(self.box, text="Primeira vez neste computador", bg=COR_FUNDO,
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                         sticky="w", pady=(0, 2))
            tk.Label(self.box, text="Guarde sua chave de administrador uma vez. "
                                    "Depois, so a senha.  No endereco, use so a base "
                                    "— sem /mcp no final.",
                     bg=COR_FUNDO, fg="#8a8a86",
                     font=("Segoe UI", 8)).grid(row=1, column=0, columnspan=3,
                                                sticky="w", pady=(0, 8))
            campos = [("servidor", "Endereco do servidor", False),
                      ("token", "Sua chave de administrador (nlm_...)", True),
                      ("senha", "Crie uma senha", True),
                      ("senha2", "Repita a senha", True)]
            acao, texto = self._registrar, "Guardar e entrar"
            self.portatil = tk.BooleanVar(value=False)
        else:
            tk.Label(self.box, text="Entrar", bg=COR_FUNDO,
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                         sticky="w", pady=(0, 2))
            origem = ("chave lida do pendrive (ao lado do programa)"
                      if cofre.e_portatil() else "chave guardada neste computador")
            tk.Label(self.box, text=origem, bg=COR_FUNDO, fg="#8a8a86",
                     font=("Segoe UI", 8)).grid(row=1, column=0, columnspan=3,
                                                sticky="w", pady=(0, 8))
            campos = [("senha", "Sua senha", True)]
            acao, texto = self._entrar, "Entrar"

        self.campos = {}
        linha = 2
        for chave, rotulo, oculto in campos:
            tk.Label(self.box, text=rotulo, bg=COR_FUNDO,
                     font=("Segoe UI", 9, "bold")).grid(row=linha, column=0, sticky="w")
            e = tk.Entry(self.box, width=46, font=("Segoe UI", 10), relief="solid",
                         bd=1, show="•" if oculto else "")
            e.grid(row=linha + 1, column=0, columnspan=2, sticky="w", pady=(0, 6))
            self.campos[chave] = e
            linha += 2

        if primeira_vez:
            tk.Checkbutton(
                self.box, variable=self.portatil, bg=COR_FUNDO,
                font=("Segoe UI", 9),
                text="Guardar ao lado deste programa (pendrive), nao neste computador"
            ).grid(row=linha, column=0, columnspan=2, sticky="w", pady=(2, 0))
            tk.Label(self.box, text="Marque se este programa esta num pendrive: a chave "
                                    "viaja junto e nao fica na maquina emprestada.",
                     bg=COR_FUNDO, fg="#8a8a86", font=("Segoe UI", 8),
                     wraplength=420, justify="left").grid(row=linha + 1, column=0,
                                                          columnspan=2, sticky="w",
                                                          pady=(0, 6))
            linha += 2

        b = tk.Button(self.box, text=texto, command=acao, font=("Segoe UI", 10, "bold"),
                      bg="#2f6fb0", fg="white", relief="flat", cursor="hand2",
                      padx=20, pady=5)
        b.grid(row=linha, column=0, sticky="w", pady=(2, 6))

        if not primeira_vez:
            tk.Button(self.box, text="Esquecer este computador",
                      command=self._esquecer, font=("Segoe UI", 9), bg=COR_FUNDO,
                      fg="#8a8a86", relief="flat", cursor="hand2",
                      bd=0).grid(row=linha, column=1, sticky="w", padx=(10, 0))

        primeiro = self.campos[campos[0][0]]
        primeiro.focus_set()
        for e in self.campos.values():
            e.bind("<Return>", lambda _: acao())

    def _registrar(self):
        v = {k: e.get().strip() for k, e in self.campos.items()}
        servidor = v.get("servidor") or SERVIDOR_PADRAO
        if not servidor or not v["token"] or not v["senha"]:
            messagebox.showwarning("Faltou preencher",
                                   "Preencha servidor, chave e senha.")
            return
        if v["senha"] != v["senha2"]:
            messagebox.showwarning("Senhas diferentes", "As duas senhas nao batem.")
            return
        if len(v["senha"]) < 8:
            messagebox.showwarning("Senha curta",
                                   "Use ao menos 8 caracteres. Ela protege uma chave "
                                   "que da acesso administrativo ao acervo.")
            return
        # Valida a chave ANTES de guardar: cofre com credencial invalida faria a
        # pessoa culpar a senha depois, e nao ha como distinguir os dois erros.
        self._diz("Conferindo a chave com o servidor...")
        api = Api(servidor, v["token"])
        self._async(api.equipe,
                    lambda eq: self._concluir_registro(api, v, servidor, eq))

    def _concluir_registro(self, api, v, servidor, equipe):
        if self.portatil.get() and cofre.dentro_de_repositorio():
            if not messagebox.askyesno(
                    "Atencao: pasta versionada",
                    "Este programa esta dentro de um repositorio git.\n\n"
                    "O cofre seria gravado aqui e poderia acabar enviado junto "
                    "com o codigo — sua chave de administrador num servidor de "
                    "codigo, protegida so pela senha.\n\n"
                    "Para o modo pendrive, copie o programa para o pendrive "
                    "primeiro.\n\nGravar aqui mesmo assim?"):
                return
        try:
            destino = cofre.gravar(v["senha"], servidor, v["token"],
                                   portatil=self.portatil.get())
        except OSError as e:
            # Pendrive somente-leitura, removido no meio, ou sem permissao.
            messagebox.showerror(
                "Nao consegui gravar",
                f"{e}\n\nSe o programa esta num pendrive, confira se ele nao "
                "esta protegido contra gravacao.")
            return
        self.api = api
        self._monta_acesso()
        self._mostrar_equipe(equipe)
        onde = "no pendrive" if self.portatil.get() else "neste computador"
        self._diz(f"Chave guardada {onde}: {destino}", COR_OK)

    def _entrar(self):
        senha = self.campos["senha"].get()
        if not senha:
            return
        try:
            servidor, token = cofre.abrir(senha)
        except cofre.SenhaErrada:
            self._diz("Senha incorreta.", COR_ERRO)
            self.campos["senha"].delete(0, "end")
            return
        except Exception as e:                                  # noqa: BLE001
            messagebox.showerror(
                "Cofre ilegivel",
                f"Nao consegui ler o cofre ({e}).\n\n"
                "Use 'Esquecer este computador' e registre de novo.")
            return
        self.api = Api(servidor, token)
        self._diz("Entrando...")
        self._carregar_equipe()

    def _esquecer(self):
        if not messagebox.askyesno(
                "Esquecer este computador",
                "Apagar a chave guardada aqui?\n\n"
                "Voce precisara da chave de administrador de novo para registrar. "
                "O acesso em si nao e revogado — isso se faz no servidor."):
            return
        cofre.apagar()
        self.api = None
        self._habilita(False)
        self.tabela.delete(*self.tabela.get_children())
        self._monta_acesso()
        self._diz("Cofre apagado.")

    def _carregar_equipe(self):
        if not self.api:
            return
        self._diz("Carregando equipe...")
        self._async(self.api.equipe, self._mostrar_equipe)

    def _mostrar_equipe(self, equipe):
        self.tabela.delete(*self.tabela.get_children())
        pendentes = 0
        for u in equipe:
            ativo = u.get("ativo")
            tem_sessao = u.get("tem_token")
            if not ativo:
                situacao = "pendente" if tem_sessao else "inativo"
                pendentes += 1 if tem_sessao else 0
            else:
                situacao = "ativo" if tem_sessao else "ativo, sem sessao"
            self.tabela.insert("", "end", values=(u.get("email", ""), u.get("nome", ""),
                                                  u.get("nivel", ""), situacao))
        self._habilita(True)
        msg = f"{len(equipe)} pessoa(s)."
        if pendentes:
            msg += f"  {pendentes} aguardando liberacao."
        self._diz(msg, COR_ATENCAO if pendentes else COR_OK)

    def _selecionado(self) -> str | None:
        sel = self.tabela.selection()
        if not sel:
            messagebox.showinfo("Selecione", "Escolha uma pessoa na lista.")
            return None
        return self.tabela.item(sel[0])["values"][0]

    def _convidar(self):
        d = Dialogo(self, "Convidar pessoa")
        if not d.email:
            return
        self._diz(f"Emitindo convite para {d.email}...")
        self._async(lambda: self.api.convidar(d.email, d.horas),
                    lambda r: JanelaConvite(self, r["email"], r["onboarding_token"], d.horas))

    def _alterar(self):
        email = self._selecionado()
        if not email:
            return
        d = DialogoNivel(self, email)
        if not d.confirmado:
            return
        self._diz(f"Atualizando {email}...")
        self._async(lambda: self.api.definir_acesso(email, d.nivel, True),
                    lambda r: (self._diz(f"{email}: acesso liberado como {d.nivel}.", COR_OK),
                               self._carregar_equipe()))

    def _revogar(self):
        email = self._selecionado()
        if not email:
            return
        if not messagebox.askyesno(
                "Revogar acesso",
                f"Revogar o acesso de {email}?\n\n"
                "A pessoa perde o acesso imediatamente e o token de API dela e apagado.\n\n"
                "A sessao Google guardada continua no banco ate ser sobrescrita — se a "
                "pessoa saiu da organizacao, peca a equipe tecnica para remove-la."):
            return
        self._diz(f"Revogando {email}...")
        self._async(lambda: self.api.definir_acesso(email, "juridico", False),
                    lambda r: (self._diz(f"{email}: acesso revogado.", COR_OK),
                               self._carregar_equipe()))


class Dialogo(tk.Toplevel):
    """Pede email e validade do convite."""

    def __init__(self, pai, titulo):
        super().__init__(pai)
        self.title(titulo)
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.email = ""
        self.horas = 48
        self.transient(pai)
        self.grab_set()

        tk.Label(self, text="Email da pessoa", bg=COR_FUNDO,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w",
                                                    padx=16, pady=(16, 2))
        self.e = tk.Entry(self, width=40, font=("Segoe UI", 10), relief="solid", bd=1)
        self.e.grid(row=1, column=0, padx=16)
        self.e.focus_set()

        tk.Label(self, text="Validade do convite (horas)", bg=COR_FUNDO,
                 font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w",
                                                    padx=16, pady=(10, 2))
        self.h = tk.Entry(self, width=10, font=("Segoe UI", 10), relief="solid", bd=1)
        self.h.insert(0, "48")
        self.h.grid(row=3, column=0, sticky="w", padx=16)

        tk.Button(self, text="Gerar convite", command=self._ok, bg="#2f6fb0",
                  fg="white", relief="flat", font=("Segoe UI", 10, "bold"),
                  cursor="hand2", pady=6).grid(row=4, column=0, sticky="we",
                                               padx=16, pady=16)
        self.bind("<Return>", lambda _: self._ok())
        pai.wait_window(self)

    def _ok(self):
        email = self.e.get().strip()
        if "@" not in email:
            messagebox.showwarning("Email invalido", "Confira o email.", parent=self)
            return
        try:
            horas = int(self.h.get().strip())
            if horas < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Validade invalida",
                                   "Informe um numero de horas.", parent=self)
            return
        self.email, self.horas = email, horas
        self.destroy()


class DialogoNivel(tk.Toplevel):
    """Escolhe o nivel ao liberar acesso."""

    def __init__(self, pai, email):
        super().__init__(pai)
        self.title("Alterar acesso")
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.confirmado = False
        self.nivel = "juridico"
        self.transient(pai)
        self.grab_set()

        tk.Label(self, text=email, bg=COR_FUNDO,
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w",
                                                     padx=16, pady=(16, 8))
        tk.Label(self, text="Nivel de acesso", bg=COR_FUNDO,
                 font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", padx=16)

        self.var = tk.StringVar(value="juridico")
        for i, (n, desc) in enumerate([
                ("admin", "tudo, incluindo gerir usuarios"),
                ("gestor", "tudo em leitura, mais adicionar fontes"),
                ("juridico", "notebooks de juridico e processos"),
                ("financeiro", "notebooks de financeiro")]):
            f = tk.Frame(self, bg=COR_FUNDO)
            f.grid(row=2 + i, column=0, sticky="w", padx=16)
            tk.Radiobutton(f, text=n, variable=self.var, value=n, bg=COR_FUNDO,
                           font=("Segoe UI", 10)).pack(side="left")
            tk.Label(f, text=f"— {desc}", bg=COR_FUNDO, fg="#8a8a86",
                     font=("Segoe UI", 8)).pack(side="left")

        tk.Label(self, text="Juridico e financeiro sao areas paralelas: nenhuma "
                            "contem a outra.", bg=COR_FUNDO, fg="#8a8a86",
                 font=("Segoe UI", 8), wraplength=330,
                 justify="left").grid(row=7, column=0, sticky="w", padx=16, pady=(8, 0))

        tk.Button(self, text="Liberar acesso", command=self._ok, bg="#2f7d5d",
                  fg="white", relief="flat", font=("Segoe UI", 10, "bold"),
                  cursor="hand2", pady=6).grid(row=8, column=0, sticky="we",
                                               padx=16, pady=16)
        pai.wait_window(self)

    def _ok(self):
        self.nivel = self.var.get()
        self.confirmado = True
        self.destroy()


class JanelaConvite(tk.Toplevel):
    """
    Mostra o convite com botao de copiar.

    O codigo pode ir por canal comum — WhatsApp, email interno. E de uso unico,
    ligado aquele email, expira, e NAO concede privilegio: quem o usa entra
    inativo, e a liberacao continua sendo decisao de um admin.
    """

    def __init__(self, pai, email, token, horas):
        super().__init__(pai)
        self.title("Convite gerado")
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.transient(pai)

        tk.Label(self, text="Convite gerado", bg=COR_FUNDO,
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2,
                                                     sticky="w", padx=16, pady=(16, 2))
        tk.Label(self, text=f"para {email} · vale {horas}h · uso unico",
                 bg=COR_FUNDO, fg="#5a5a56",
                 font=("Segoe UI", 9)).grid(row=1, column=0, columnspan=2,
                                            sticky="w", padx=16, pady=(0, 10))

        cx = tk.Text(self, height=2, width=52, font=("Consolas", 9), wrap="char",
                     relief="solid", bd=1)
        cx.insert("1.0", token)
        cx.configure(state="disabled")
        cx.grid(row=2, column=0, columnspan=2, padx=16)

        def copiar():
            self.clipboard_clear()
            self.clipboard_append(token)
            b.configure(text="Copiado!", bg=COR_OK)
            self.after(1500, lambda: b.configure(text="Copiar codigo", bg="#2f6fb0"))

        b = tk.Button(self, text="Copiar codigo", command=copiar, bg="#2f6fb0",
                      fg="white", relief="flat", font=("Segoe UI", 10, "bold"),
                      cursor="hand2", pady=6)
        b.grid(row=3, column=0, sticky="we", padx=(16, 4), pady=12)
        tk.Button(self, text="Fechar", command=self.destroy, bg="#e8e8e5",
                  relief="flat", font=("Segoe UI", 10), cursor="hand2",
                  pady=6).grid(row=3, column=1, sticky="we", padx=(4, 16), pady=12)

        tk.Label(self, text="Mande para a pessoa. Ela abre o Conector, cola o codigo e "
                            "faz o login Google. Depois volte aqui e libere o acesso.",
                 bg=COR_FUNDO, fg="#5a5a56", font=("Segoe UI", 9), wraplength=420,
                 justify="left").grid(row=4, column=0, columnspan=2, sticky="w",
                                      padx=16, pady=(0, 16))


if __name__ == "__main__":
    App().mainloop()
