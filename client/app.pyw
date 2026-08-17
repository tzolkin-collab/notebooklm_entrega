# -*- coding: utf-8 -*-
"""
Conector NotebookLM — janela de onboarding.

Existe para tirar o terminal do caminho. O fluxo por linha de comando exige
definir tres variaveis de ambiente e lembrar dois argumentos; numa maquina
compartilhada, usada uma vez por pessoa, isso e a diferenca entre o onboarding
acontecer e nao acontecer.

NAO reimplementa nada: coleta os dados, chama o connect.py como subprocesso e
mostra a saida dele. O connect.py continua sendo o unico caminho — o que e
testado e o que roda.

Extensao .pyw: abre sem janela preta de console atras.

Requer apenas a biblioteca padrao (tkinter). O Playwright e o CLI notebooklm sao
verificados na abertura e instalados sob confirmacao.
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

AQUI = os.path.dirname(os.path.abspath(__file__))

# Preencher no empacotamento, junto com o <PUBLIC_URL> do plugin.json e do
# SKILL.md. Se ficar vazio, o campo aparece editavel na janela.
SERVIDOR_PADRAO = ""

COR_FUNDO = "#f4f4f2"
COR_OK = "#2f7d5d"
COR_ERRO = "#b03a2e"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Conector NotebookLM")
        self.configure(bg=COR_FUNDO)
        self.resizable(False, False)
        self.fila = queue.Queue()
        self.rodando = False
        self._monta()
        self.after(100, self._drena_fila)

    # ── interface ────────────────────────────────────────────────────────────
    def _monta(self):
        pad = dict(padx=16, pady=(0, 2))
        tk.Label(self, text="Conectar ao NotebookLM", bg=COR_FUNDO,
                 font=("Segoe UI", 15, "bold")).grid(row=0, column=0, columnspan=2,
                                                     sticky="w", padx=16, pady=(16, 2))
        tk.Label(self, text="Voce fara login com a sua conta Google. Leva uns 2 minutos.",
                 bg=COR_FUNDO, fg="#5a5a56", font=("Segoe UI", 9),
                 wraplength=440, justify="left").grid(row=1, column=0, columnspan=2,
                                                      sticky="w", padx=16, pady=(0, 12))

        self.campos = {}
        linhas = [
            ("email", "Seu email Google", "o mesmo que voce usa no NotebookLM"),
            ("nome", "Seu nome completo", ""),
            ("token", "Codigo de acesso", "peca ao administrador; vale uma vez"),
        ]
        if not SERVIDOR_PADRAO:
            linhas.insert(0, ("servidor", "Endereco do servidor", "https://..."))

        r = 2
        for chave, rotulo, dica in linhas:
            tk.Label(self, text=rotulo, bg=COR_FUNDO,
                     font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w", **pad)
            e = tk.Entry(self, width=52, font=("Segoe UI", 10), relief="solid", bd=1)
            e.grid(row=r + 1, column=0, columnspan=2, sticky="we", padx=16, pady=(0, 2))
            self.campos[chave] = e
            if dica:
                tk.Label(self, text=dica, bg=COR_FUNDO, fg="#8a8a86",
                         font=("Segoe UI", 8)).grid(row=r + 2, column=0, sticky="w",
                                                    padx=16, pady=(0, 8))
                r += 3
            else:
                r += 2

        self.botao = tk.Button(self, text="Conectar", command=self._iniciar,
                               font=("Segoe UI", 11, "bold"), bg="#2f6fb0", fg="white",
                               relief="flat", cursor="hand2", pady=8)
        self.botao.grid(row=r, column=0, columnspan=2, sticky="we", padx=16, pady=(8, 4))

        self.status = tk.Label(self, text="", bg=COR_FUNDO, font=("Segoe UI", 9, "bold"))
        self.status.grid(row=r + 1, column=0, columnspan=2, sticky="w", padx=16)

        self.log = tk.Text(self, height=11, width=62, font=("Consolas", 8),
                           bg="#ffffff", relief="solid", bd=1, state="disabled", wrap="word")
        self.log.grid(row=r + 2, column=0, columnspan=2, padx=16, pady=(6, 16), sticky="we")

        self.campos[list(self.campos)[0]].focus_set()

    def _escreve(self, txt):
        self.log.configure(state="normal")
        self.log.insert("end", txt)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ── execucao ─────────────────────────────────────────────────────────────
    def _iniciar(self):
        if self.rodando:
            return
        v = {k: e.get().strip() for k, e in self.campos.items()}
        servidor = v.get("servidor") or SERVIDOR_PADRAO

        faltando = [r for k, r in [("email", "email"), ("nome", "nome"),
                                   ("token", "codigo de acesso")] if not v.get(k)]
        if not servidor:
            faltando.append("endereco do servidor")
        if faltando:
            messagebox.showwarning("Faltou preencher", "Preencha: " + ", ".join(faltando))
            return
        if "@" not in v["email"]:
            messagebox.showwarning("Email invalido", "Confira o email.")
            return

        self.rodando = True
        self.botao.configure(state="disabled", text="Conectando...")
        self.status.configure(text="Abrindo o navegador para o login...", fg="#5a5a56")
        self.log.configure(state="normal"); self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        threading.Thread(target=self._trabalha, args=(servidor, v), daemon=True).start()

    def _trabalha(self, servidor, v):
        env = dict(os.environ)
        env["NOTEBOOKLM_SERVER_URL"] = servidor
        env["NOTEBOOKLM_ONBOARDING_TOKEN"] = v["token"]
        env["PYTHONIOENCODING"] = "utf-8"

        cmd = [sys.executable, os.path.join(AQUI, "connect.py"),
               "--email", v["email"], "--nome", v["nome"]]
        try:
            p = subprocess.Popen(cmd, cwd=AQUI, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                 errors="replace", bufsize=1,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for linha in p.stdout:
                self.fila.put(("log", linha))
            p.wait()
            self.fila.put(("fim", p.returncode))
        except FileNotFoundError:
            self.fila.put(("log", "\nERRO: connect.py nao encontrado ao lado deste app.\n"))
            self.fila.put(("fim", 1))
        except Exception as e:                                  # noqa: BLE001
            self.fila.put(("log", f"\nERRO inesperado: {e}\n"))
            self.fila.put(("fim", 1))

    def _drena_fila(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self._escreve(dado)
                else:
                    self._finaliza(dado)
        except queue.Empty:
            pass
        self.after(100, self._drena_fila)

    def _finaliza(self, codigo):
        self.rodando = False
        self.botao.configure(state="normal", text="Conectar")
        if codigo == 0:
            self.status.configure(text="Pronto. Avise o administrador para liberar seu acesso.",
                                  fg=COR_OK)
            messagebox.showinfo(
                "Conectado",
                "Sua conta foi enviada com sucesso.\n\n"
                "O cadastro entra pendente: um administrador precisa liberar seu acesso.\n"
                "Depois disso, o NotebookLM aparece no Claude.")
        else:
            self.status.configure(text="Nao deu certo. Veja a mensagem abaixo.", fg=COR_ERRO)


def dependencias_ok():
    """
    O connect.py chama o executavel `notebooklm`. Se ele nao existir, o erro sai
    como 'arquivo nao encontrado' no meio do processo — confuso para quem so
    queria clicar um botao. Melhor detectar antes e oferecer a instalacao.
    """
    from shutil import which
    return which("notebooklm") is not None


def instala(janela_pai=None):
    req = os.path.join(AQUI, "requirements.txt")
    passos = [
        ([sys.executable, "-m", "pip", "install", "-r", req], "bibliotecas"),
        ([sys.executable, "-m", "playwright", "install", "chromium"], "navegador"),
    ]
    for cmd, nome in passos:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            messagebox.showerror(
                "Instalacao falhou",
                f"Nao consegui instalar as {nome}.\n\n"
                f"{(r.stderr or r.stdout)[-400:]}")
            return False
    return True


if __name__ == "__main__":
    raiz = tk.Tk(); raiz.withdraw()
    if not dependencias_ok():
        if not messagebox.askyesno(
                "Primeira vez neste computador",
                "Faltam alguns componentes (cerca de 150 MB).\n\n"
                "Instalar agora? Leva uns minutos e so acontece uma vez."):
            sys.exit(0)
        if not instala():
            sys.exit(1)
    raiz.destroy()
    App().mainloop()
