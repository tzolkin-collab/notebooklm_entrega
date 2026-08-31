# -*- coding: utf-8 -*-
"""
Setup do NotebookLM Connector — lado CLIENTE (máquina de usuário final).

Seguro por design: o cliente NUNCA recebe a chave Fernet nem a DATABASE_URL.
Ele só instala as dependências e faz login Google; o token é enviado por HTTPS
ao servidor, que cifra e cria o cadastro (pendente de ativação por um admin).

Uso:
    set NOTEBOOKLM_ONBOARDING_TOKEN=<token de uso único — peça ao admin>
    python setup.py
"""

import os
import subprocess
import sys
import pathlib


def run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        # A falha e reportada com o comando e o codigo de saida, que e o que
        # permite diagnosticar.
        sys.exit(f"\nERRO: o comando abaixo falhou (codigo {e.returncode}):\n"
                 f"  {' '.join(cmd)}\n")


def main():
    print("\n=== NotebookLM Connector - Setup do cliente ===\n")

    # A conferencia vem antes do passo 1: o passo 2 baixa um Chromium de
    # ~150 MB, e tudo que puder ser validado deve ser validado antes dele.
    if not os.getenv("NOTEBOOKLM_ONBOARDING_TOKEN"):
        print("ERRO: defina o token de onboarding (uso único) antes de rodar:")
        print('  set NOTEBOOKLM_ONBOARDING_TOKEN=<peça ao admin>\n')
        sys.exit(1)

    print("[1/3] Instalando dependencias Python...")
    run([sys.executable, "-m", "pip", "install", "-r",
         str(pathlib.Path(__file__).parent / "requirements.txt")])

    print("\n[2/3] Instalando Chromium (Playwright)...")
    run([sys.executable, "-m", "playwright", "install", "chromium"])

    print("\n[3/3] Login Google + envio do token ao servidor...")
    email = input("  Email Google do NotebookLM: ").strip()
    nome = input("  Nome completo: ").strip()
    connect = pathlib.Path(__file__).parent / "connect.py"
    run([sys.executable, str(connect), "--email", email, "--nome", nome])

    print("\nSetup concluido.")
    print("Seu cadastro está PENDENTE — um admin precisa ativar seu acesso")
    print("e te enviar o token de API (para n8n/automações), se aplicável.")
    print("No Claude, use o conector MCP (login Google) — não precisa de token manual.")


if __name__ == "__main__":
    main()
