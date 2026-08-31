# -*- coding: utf-8 -*-
"""
Painel de administracao do conector NotebookLM.

Convidar alguem, ativar, mudar nivel e revogar — em janela, no lugar de
requisicoes HTTP a mao. Quem administra o acervo de um escritorio nao deveria
precisar de linha de comando para liberar o acesso de uma pessoa nova.

Fala com a API REST, nao com o banco. Isso importa por tres motivos: usa o mesmo
caminho ja testado, respeita o gate de nivel do servidor (o painel nao pode dar
mais acesso do que o token de quem o abriu), e nao exige a chave Fernet nem a
DATABASE_URL na maquina de quem administra.

Extensao .pyw: abre sem console atras. Fora da biblioteca padrao, so depende de
`cryptography`, usada pelo cofre local (cofre.py).
"""
import json
import os
import pathlib
import queue
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import filedialog, messagebox, ttk

try:
    import cofre
except ImportError as erro:
    # Sob pythonw nao ha console, e o stderr do processo nao tem para onde ir.
    # A caixa de dialogo abaixo e o canal por onde a falta de um componente
    # chega a quem abriu o programa.
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

# O escritorio tem um servidor so. O endereco fica embutido para que quem
# administra nao precise informar um valor que nao muda. Deixar vazio faz o
# campo reaparecer na tela, para apontar a outro ambiente.
SERVIDOR_PADRAO = "https://connectors-notebooklm.tpgavy.easypanel.host"

NIVEIS = ["admin", "gestor", "juridico", "financeiro"]

COR_FUNDO = "#f4f4f2"
COR_OK = "#2f7d5d"
COR_ERRO = "#b03a2e"
COR_ATENCAO = "#a8791c"


def normalizar_servidor(url: str) -> str:
    """
    Aceita qualquer forma da URL que a pessoa tenha a mao.

    O endereco do conector do Claude termina em /mcp e o da API REST em /api; o
    painel monta os proprios caminhos a partir da base. Os dois sufixos e as
    barras sobrando sao removidos aqui.
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

    def quem_sou_eu(self):
        """
        De quem e a chave em uso.

        O /auth/check identifica pelo proprio token e devolve o email em qualquer
        desfecho — inclusive com a sessao Google expirada, caso em que o status
        vem diferente mas o email continua la.
        """
        return self._req("/auth/check")

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
        self._tarefa = None
        self._monta()
        self._tarefa = self.after(100, self._drena)

    # ── interface ────────────────────────────────────────────────────────────
    def _monta(self):
        tk.Label(self, text="Administracao de acessos", bg=COR_FUNDO,
                 font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=4,
                                                     sticky="w", padx=16, pady=(16, 2))

        # A ordem importa: liberar pressupoe que a pessoa ja tenha feito o
        # login dela. Por isso ela fica escrita na tela.
        tk.Label(self,
                 text="1. Convide a pessoa e mande o codigo   →   "
                      "2. Ela faz o login dela no Conector   →   "
                      "3. Voce libera e escolhe o nivel",
                 bg=COR_FUNDO, fg="#6b6b66", font=("Segoe UI", 9)
                 ).grid(row=0, column=0, columnspan=4, sticky="w",
                        padx=16, pady=(46, 12))

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
        # Os quatro botoes nao tem o mesmo peso: convidar e o que mais se faz,
        # revogar e irreversivel. A cor carrega essa diferenca, para a tela
        # sugerir o caminho comum e sinalizar o que exige atencao.
        for txt, cmd, fundo, frente, peso in [
                ("Convidar pessoa", self._convidar, "#2f6fb0", "white", "bold"),
                ("Alterar acesso", self._alterar, "#e8e8e5", "#2a2a28", "normal"),
                ("Revogar acesso", self._revogar, "#f2e3e1", COR_ERRO, "normal"),
                ("Atualizar", self._carregar_equipe, "#e8e8e5", "#6b6b66", "normal")]:
            b = tk.Button(acoes, text=txt, command=cmd,
                          font=("Segoe UI", 10, peso),
                          relief="flat", bg=fundo, fg=frente, cursor="hand2",
                          padx=14, pady=6, state="disabled")
            b.pack(side="left", padx=(0, 8))
            self.botoes.append(b)

        self.status = tk.Label(self, text="Entre com sua chave de administrador para ver a equipe.",
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
        # O `after` so se reagenda enquanto a janela existe, o que mantem o Tk
        # sem callbacks pendentes depois que ela e fechada.
        if not self.winfo_exists():
            return
        self._tarefa = None
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
        self._tarefa = self.after(100, self._drena)

    def destroy(self):
        # O `after` pendente e cancelado aqui: uma vez destruida a janela, o Tk
        # nao tem mais o comando para chamar quando o prazo vence.
        if self._tarefa is not None:
            self.after_cancel(self._tarefa)
            self._tarefa = None
        super().destroy()

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
                                    "Depois, so a senha.",
                     bg=COR_FUNDO, fg="#8a8a86",
                     font=("Segoe UI", 8)).grid(row=1, column=0, columnspan=3,
                                                sticky="w", pady=(0, 8))
            campos = [("token", "Sua chave de administrador (nlm_...)", True),
                      ("senha", "Crie uma senha", True),
                      ("senha2", "Repita a senha", True)]
            # So pergunta o endereco se nao houver um embutido: num escritorio
            # com um servidor so, o valor e sempre o mesmo.
            if not SERVIDOR_PADRAO:
                campos.insert(0, ("servidor", "Endereco do servidor", False))
            acao, texto = self._registrar, "Guardar e entrar"
            self.trocar_chave = tk.BooleanVar(value=True)
            self.pasta_escolhida: pathlib.Path | None = None
        else:
            tk.Label(self.box, text="Entrar", bg=COR_FUNDO,
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                         sticky="w", pady=(0, 2))
            tk.Label(self.box, text=cofre.onde_esta(), bg=COR_FUNDO, fg="#8a8a86",
                     font=("Segoe UI", 8)).grid(row=1, column=0, columnspan=3,
                                                sticky="w", pady=(0, 8))
            campos = [("senha", "Sua senha", True)]
            acao, texto = self._entrar, "Entrar"
            self._avisa_chave_duplicada()

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
            linha = self._monta_destino(linha)

            tk.Checkbutton(
                self.box, variable=self.trocar_chave, bg=COR_FUNDO,
                font=("Segoe UI", 9),
                text="Trocar por uma chave nova, que so este cofre conhece"
            ).grid(row=linha, column=0, columnspan=2, sticky="w", pady=(2, 0))
            tk.Label(self.box, text="A chave que voce colou acima veio por algum canal e "
                                    "ficou guardada em algum lugar. Marcado, o painel pede "
                                    "uma nova ao servidor e sela no cofre: a colada para de "
                                    "funcionar, e a copia dela deixa de valer. Desmarque se "
                                    "voce usa essa mesma chave em alguma automacao.",
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

    def _avisa_chave_duplicada(self):
        """
        Duas credenciais que funcionam sozinhas anulam o sentido de levar a
        chave no pendrive: retirado o pendrive, a que ficou na maquina continua
        abrindo o painel. O aviso so aparece quando as duas existem.
        """
        if not (cofre.e_portatil() and cofre.tem_cofre_local()):
            return
        f = tk.Frame(self.box, bg="#fdf6e3")
        f.grid(row=90, column=0, columnspan=3, sticky="we", pady=(6, 0))
        tk.Label(f, text="Ha tambem uma chave guardada neste computador.",
                 bg="#fdf6e3", fg=COR_ATENCAO,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
        tk.Label(f, text="Enquanto ela existir, tirar o pendrive nao tira o acesso "
                         "daqui: sao duas credenciais independentes.",
                 bg="#fdf6e3", fg="#6b6b66", font=("Segoe UI", 8),
                 wraplength=400, justify="left").pack(anchor="w", padx=8)

        def apagar():
            if messagebox.askyesno(
                    "Apagar a chave deste computador",
                    "A chave que voce carrega continua valendo. Some apenas a "
                    "copia guardada na pasta deste usuario." + chr(10) + chr(10) +
                    "Apagar?"):
                cofre.apagar_local()
                self._monta_acesso()
                self._diz("Chave deste computador apagada.", COR_OK)

        tk.Button(f, text="Apagar a deste computador", command=apagar,
                  bg="#f2e3e1", fg=COR_ERRO, relief="flat", font=("Segoe UI", 9),
                  cursor="hand2", padx=10, pady=4).pack(anchor="w", padx=8, pady=(4, 8))

    def _monta_destino(self, linha: int) -> int:
        """
        Onde o cofre vai ficar. Qualquer pasta serve; a removivel vem marcada.

        A lista e montada na hora, a partir das unidades plugadas neste momento,
        e nao de um caminho guardado: letra de pendrive muda de porta para porta.
        """
        tk.Label(self.box, text="Onde guardar a chave", bg=COR_FUNDO,
                 font=("Segoe UI", 9, "bold")).grid(row=linha, column=0,
                                                    columnspan=2, sticky="w",
                                                    pady=(4, 2))
        linha += 1

        pendrives = cofre.destinos_de_pendrive()
        self.destino = tk.StringVar(value=str(pendrives[0]) if pendrives else "local")

        opcoes = [(str(p), f"Pendrive {p.drive or p.parent}", "recomendado")
                  for p in pendrives]
        opcoes.append(("local", "Neste computador", ""))
        opcoes.append(("outra", "Outra pasta...", ""))

        for valor, rotulo, nota in opcoes:
            f = tk.Frame(self.box, bg=COR_FUNDO)
            f.grid(row=linha, column=0, columnspan=2, sticky="w")
            tk.Radiobutton(f, text=rotulo, variable=self.destino, value=valor,
                           command=self._destino_mudou, bg=COR_FUNDO,
                           font=("Segoe UI", 9)).pack(side="left")
            if nota:
                tk.Label(f, text=nota, bg=COR_FUNDO, fg=COR_OK,
                         font=("Segoe UI", 8, "bold")).pack(side="left")
            linha += 1

        self.rotulo_destino = tk.Label(
            self.box,
            text=("A chave anda com o pendrive e nao fica na maquina."
                  if pendrives else
                  "Sem pendrive plugado. Guardar num removivel deixa a maquina "
                  "sem credencial quando ele sai — plugue um e reabra o painel "
                  "para ve-lo aqui."),
            bg=COR_FUNDO, fg="#8a8a86", font=("Segoe UI", 8),
            wraplength=420, justify="left")
        self.rotulo_destino.grid(row=linha, column=0, columnspan=2, sticky="w",
                                 pady=(2, 6))
        return linha + 1

    def _destino_mudou(self):
        if self.destino.get() != "outra":
            self.pasta_escolhida = None
            if self.destino.get() == "local":
                self.rotulo_destino.configure(
                    text="A chave fica na sua pasta de usuario, neste computador.")
            else:
                self.rotulo_destino.configure(
                    text="A chave anda com o pendrive e nao fica na maquina.")
            return
        escolhida = filedialog.askdirectory(title="Pasta onde guardar a chave",
                                            parent=self)
        if not escolhida:
            self.destino.set("local")
            self._destino_mudou()
            return
        self.pasta_escolhida = pathlib.Path(escolhida)
        self.rotulo_destino.configure(
            text=f"A chave vai para {self.pasta_escolhida}")

    def _destino_do_cofre(self) -> tuple[pathlib.Path | None, bool]:
        """
        (caminho do cofre, escolha valida). None de caminho significa o padrao,
        que e a pasta do usuario deste computador.
        """
        v = self.destino.get()
        if v == "local":
            return None, True
        if v == "outra":
            if not self.pasta_escolhida:
                messagebox.showwarning("Faltou a pasta",
                                       "Escolha a pasta onde a chave vai ficar.")
                return None, False
            return self.pasta_escolhida / cofre.NOME_ARQUIVO, True
        return pathlib.Path(v), True

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
        # A chave e conferida com o servidor antes de ir para o cofre, para que
        # o que fica guardado seja sempre uma credencial que funciona.
        self._diz("Conferindo a chave com o servidor...")
        api = Api(servidor, v["token"])
        self._async(api.equipe,
                    lambda eq: self._concluir_registro(api, v, servidor, eq))

    def _concluir_registro(self, api, v, servidor, equipe):
        # Lidos agora porque o _monta_acesso() adiante refaz a tela de registro.
        alvo, valido = self._destino_do_cofre()
        if not valido:
            return
        trocar = self.trocar_chave.get()

        if alvo is not None and cofre.dentro_de_repositorio(alvo):
            if not messagebox.askyesno(
                    "Atencao: pasta versionada",
                    f"{alvo.parent}\n\nesta dentro de um repositorio git. O cofre "
                    "gravado ai pode acabar enviado junto com o codigo — sua chave "
                    "de administrador num servidor de codigo, protegida so pela "
                    "senha.\n\nGravar ai mesmo assim?"):
                return
        try:
            destino = cofre.gravar(v["senha"], servidor, v["token"], destino=alvo)
        except OSError as e:
            # Midia somente-leitura, retirada no meio, ou pasta sem permissao.
            messagebox.showerror(
                "Nao consegui gravar",
                f"{e}\n\nConfira se o lugar escolhido aceita gravacao e ainda "
                "esta acessivel.")
            return
        self.api = api
        self._mostrar_equipe(equipe)
        self._diz(f"Chave guardada em {destino}", COR_OK)

        self._monta_acesso()

        if trocar:
            # O cofre ja esta gravado e funcionando com a chave colada. A troca
            # vem depois, nesta ordem de proposito: se ela nao completar, o que
            # ficou em disco continua sendo uma credencial valida.
            self._diz("Pedindo uma chave nova ao servidor...")
            self._async(
                lambda: self._pedir_chave_nova(api),
                lambda r: self._selar_chave_nova(r, v["senha"], servidor, destino))

    def _pedir_chave_nova(self, api):
        """
        Roda em thread. Pede ao servidor a rotacao da propria credencial e
        devolve (email, chave_nova), ou (None, motivo) se nao der.

        As falhas sao devolvidas em vez de levantadas: a chave colada continua
        valendo, entao nao ha nada de grave a anunciar em caixa de erro.
        """
        try:
            email = api.quem_sou_eu().get("email")
            if not email:
                return None, "o servidor nao informou de quem e a chave"
            nova = api.definir_acesso(email, "admin", True).get("api_token")
            if not nova:
                return None, "o servidor nao devolveu uma chave nova"
            return email, nova
        except ErroApi as e:
            return None, e.amigavel()
        except Exception as e:                                  # noqa: BLE001
            return None, str(e)

    def _selar_chave_nova(self, resultado, senha, servidor, destino):
        email, nova = resultado
        if not email:
            self._diz(f"Chave guardada. A troca nao foi feita: {nova}", COR_ATENCAO)
            return
        try:
            cofre.gravar(senha, servidor, nova, destino=destino)
        except OSError as e:
            # A rotacao ja aconteceu no servidor, entao a chave anterior morreu.
            # Se a nova nao entrar no cofre, ela existe apenas nesta janela.
            JanelaSegredo(
                self, "Guarde esta chave agora",
                f"O cofre nao pode ser gravado ({e}), e a chave anterior ja nao "
                f"funciona mais.", nova,
                "Copie e guarde em lugar seguro: e com ela que voce registra "
                "este computador de novo.")
            return
        self.api = Api(servidor, nova)
        self._diz(f"Chave trocada — a que voce colou nao funciona mais.  ({email})",
                  COR_OK)

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

    def _selecionado(self) -> tuple[str, str] | None:
        """Devolve (email, nivel) da linha marcada, ou None se nao ha nenhuma."""
        sel = self.tabela.selection()
        if not sel:
            messagebox.showinfo("Selecione", "Escolha uma pessoa na lista.")
            return None
        v = self.tabela.item(sel[0])["values"]
        return str(v[0]), str(v[2])

    def _convidar(self):
        d = Dialogo(self, "Convidar pessoa")
        if not d.email:
            return
        self._diz(f"Emitindo convite para {d.email}...")
        self._async(
            lambda: self.api.convidar(d.email, d.horas),
            lambda r: JanelaSegredo(
                self, "Convite gerado",
                f"para {r['email']} · vale {d.horas}h · uso unico",
                r["onboarding_token"],
                "Mande para a pessoa. Ela abre o Conector, cola o codigo e faz o "
                "login Google. Depois volte aqui e libere o acesso. O codigo nao "
                "concede privilegio: quem o usa entra inativo."))

    def _alterar(self):
        alvo = self._selecionado()
        if not alvo:
            return
        email, _ = alvo
        d = DialogoNivel(self, email)
        if not d.confirmado:
            return
        self._diz(f"Atualizando {email}...")
        self._async(lambda: self.api.definir_acesso(email, d.nivel, True),
                    lambda r: self._acesso_liberado(email, d.nivel, r))

    def _acesso_liberado(self, email, nivel, resposta):
        self._diz(f"{email}: acesso liberado como {nivel}.", COR_OK)
        self._carregar_equipe()
        # Liberar acesso rotaciona a chave de API da pessoa, e a nova so existe
        # nesta resposta. Quem usa apenas o Claude nunca precisa dela; quem tem
        # integracao pela API REST precisa, e sem mostra-la aqui nao ha de onde
        # tira-la depois.
        nova = resposta.get("api_token")
        if nova:
            JanelaSegredo(
                self, f"Chave de API de {email}",
                "Serve so para integracoes que falam direto com a API (n8n e "
                "afins). Quem usa o acervo pelo Claude nao precisa dela.", nova,
                "A chave anterior desta pessoa parou de funcionar agora. Entregue "
                "esta a quem cuida das integracoes, ou ignore se nao houver.")

    def _revogar(self):
        alvo = self._selecionado()
        if not alvo:
            return
        email, nivel_atual = alvo
        if not messagebox.askyesno(
                "Revogar acesso",
                f"Revogar o acesso de {email}?\n\n"
                "A pessoa perde o acesso imediatamente e o token de API dela e apagado.\n\n"
                "A sessao Google guardada continua no banco ate ser sobrescrita — se a "
                "pessoa saiu da organizacao, peca a equipe tecnica para remove-la."):
            return
        self._diz(f"Revogando {email}...")
        # Revogar e desligar o acesso, nao rebaixar de area. O nivel atual vai
        # junto para que a linha continue registrando a que area a pessoa
        # pertencia — inclusive se o acesso for religado depois.
        nivel = nivel_atual if nivel_atual in NIVEIS else "juridico"
        self._async(lambda: self.api.definir_acesso(email, nivel, False),
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


class JanelaSegredo(tk.Toplevel):
    """
    Mostra um valor que o servidor devolve uma vez so, com botao de copiar.

    Serve ao convite de onboarding e as chaves de API. O que muda entre os casos
    e o texto; o valor sempre aparece inteiro, porque nao ha segunda chance de
    consulta-lo.
    """

    def __init__(self, pai, titulo, subtitulo, segredo, rodape):
        super().__init__(pai)
        self.title(titulo)
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.transient(pai)

        tk.Label(self, text=titulo, bg=COR_FUNDO,
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2,
                                                     sticky="w", padx=16, pady=(16, 2))
        tk.Label(self, text=subtitulo, bg=COR_FUNDO, fg="#5a5a56",
                 font=("Segoe UI", 9), wraplength=430,
                 justify="left").grid(row=1, column=0, columnspan=2,
                                      sticky="w", padx=16, pady=(0, 10))

        cx = tk.Text(self, height=2, width=52, font=("Consolas", 9), wrap="char",
                     relief="solid", bd=1)
        cx.insert("1.0", segredo)
        cx.configure(state="disabled")
        cx.grid(row=2, column=0, columnspan=2, padx=16)

        def copiar():
            self.clipboard_clear()
            self.clipboard_append(segredo)
            b.configure(text="Copiado!", bg=COR_OK)
            self.after(1500, lambda: b.configure(text="Copiar", bg="#2f6fb0"))

        b = tk.Button(self, text="Copiar", command=copiar, bg="#2f6fb0",
                      fg="white", relief="flat", font=("Segoe UI", 10, "bold"),
                      cursor="hand2", pady=6)
        b.grid(row=3, column=0, sticky="we", padx=(16, 4), pady=12)
        tk.Button(self, text="Fechar", command=self.destroy, bg="#e8e8e5",
                  relief="flat", font=("Segoe UI", 10), cursor="hand2",
                  pady=6).grid(row=3, column=1, sticky="we", padx=(4, 16), pady=12)

        tk.Label(self, text=rodape, bg=COR_FUNDO, fg="#5a5a56",
                 font=("Segoe UI", 9), wraplength=430,
                 justify="left").grid(row=4, column=0, columnspan=2, sticky="w",
                                      padx=16, pady=(0, 16))


if __name__ == "__main__":
    App().mainloop()
