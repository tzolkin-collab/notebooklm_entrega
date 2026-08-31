# -*- coding: utf-8 -*-
"""
Conector self-service do NotebookLM.

Faz o login Google (abre o Chromium uma vez) e envia o token automaticamente
para o servidor, que criptografa e salva no Postgres. Sem terminal complicado,
sem mexer em banco — e SEM a chave Fernet jamais tocar esta máquina.

O cadastro entra PENDENTE: um admin ativa o acesso e define o nível depois
(POST /admin/users). O nível não é escolhido aqui de propósito — auto-atribuir
nível seria escalonamento de privilégio.

Uso:
    python connect.py --email voce@escritorio.com --nome "Seu Nome"
"""

import argparse
import json
import os
import pathlib
import shutil
import re
import subprocess
import sys
import urllib.error
import urllib.request

# ── Configuracao do servidor ────────────────────────────────────────────────────
# Este script envia o storage_state (cookies da sessao Google do usuario) para
# SERVER_URL, entao o endereco precisa estar certo — e por isso ele ja vem no
# programa, em vez de digitado. A variavel de ambiente continua valendo, para
# apontar a outro ambiente sem editar o arquivo.
SERVIDOR_PADRAO = "https://connectors-notebooklm.tpgavy.easypanel.host"

SERVER_URL = (os.getenv("NOTEBOOKLM_SERVER_URL") or SERVIDOR_PADRAO).rstrip("/")
if not SERVER_URL:
    sys.exit(
        "ERRO: nao ha endereco de servidor configurado. Defina a variavel de "
        "ambiente NOTEBOOKLM_SERVER_URL com a URL do servidor da organizacao."
    )

ONBOARDING_TOKEN = os.getenv("NOTEBOOKLM_ONBOARDING_TOKEN", "")
if not ONBOARDING_TOKEN:
    sys.exit(
        "ERRO: defina a variavel de ambiente NOTEBOOKLM_ONBOARDING_TOKEN "
        "(token de uso unico, ligado ao seu email; peca ao admin)."
    )

PROFILES_DIR = pathlib.Path.home() / ".notebooklm" / "profiles"


def nome_de_perfil(bruto: str) -> str:
    """
    Reduz o texto a algo que possa ser nome de pasta.

    O perfil vira uma pasta sob PROFILES_DIR, e essa pasta e apagada ao final do
    onboarding. Como o valor vem de fora — do email digitado ou de --profile —
    ele e reduzido aqui a letras, digitos, ponto, hifen e sublinhado, de modo que
    o resultado seja sempre um unico nome de pasta.
    """
    limpo = re.sub(r"[^A-Za-z0-9._-]", "_", bruto).strip("._-")
    return limpo or "default"


def run_login(profile: str) -> None:
    """Abre o Chromium para login Google via notebooklm CLI."""
    print(f"\n[1/3] Abrindo o navegador para login Google (perfil: {profile})...")
    print("      Faca login com a conta Google que voce usa no NotebookLM.\n")
    try:
        result = subprocess.run(
            ["notebooklm", "--profile", profile, "login"],
            capture_output=False,
        )
    except FileNotFoundError:
        # O binario `notebooklm` vem do pacote notebooklm-py e e chamado por
        # subprocesso. O WinError 2 padrao nao nomeia o arquivo procurado, entao
        # a mensagem abaixo diz qual e e como instala-lo.
        print("[ERRO] O programa `notebooklm` nao esta instalado nesta maquina.")
        print()
        print("       Instale as dependencias do cliente:")
        print("         python -m pip install -r requirements.txt")
        print("         python -m playwright install chromium")
        print()
        print("       Ou rode o setup.py, que faz os dois.")
        sys.exit(1)
    if result.returncode != 0:
        print("[ERRO] Login falhou. Tente novamente.")
        sys.exit(1)


def load_storage_state(profile: str) -> dict:
    state_file = PROFILES_DIR / profile / "storage_state.json"
    if not state_file.exists():
        print(f"[ERRO] Token nao encontrado em {state_file}")
        sys.exit(1)
    return json.loads(state_file.read_text(encoding="utf-8"))


def limpar_perfil_local(profile: str) -> None:
    """
    Apaga o perfil local depois que o token ja esta no servidor.

    O storage_state.json sao os cookies da sessao Google da pessoa — dao acesso a
    CONTA INTEIRA, nao so ao NotebookLM. Enquanto ficam em disco, em texto claro,
    a maquina onde o onboarding foi feito vale mais que o servidor, que ao menos
    cifra. Numa maquina compartilhada isso se acumula: uma pessoa por perfil.

    Nao e opcional nem best-effort silencioso: se falhar, avisa em voz alta, para
    que alguem apague a mao.
    """
    base = PROFILES_DIR.resolve()
    alvo = (PROFILES_DIR / profile).resolve()
    # O apagamento fica restrito a PROFILES_DIR: o alvo e resolvido e conferido
    # antes de qualquer remocao.
    if base not in alvo.parents:
        print(f"\n  [ATENCAO] Caminho de perfil inesperado ({alvo}). Nao apaguei nada.")
        print("            Confira e apague a mao se necessario.")
        return
    try:
        shutil.rmtree(alvo)
        print(f"     Perfil local apagado: {alvo}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"\n  [ATENCAO] Nao consegui apagar {alvo} ({e}).")
        print("            Apague a mao: sao os cookies da sua conta Google.")


def upload(email: str, nome: str, state: dict, profile: str) -> None:
    print("\n[3/3] Enviando token para o servidor...")
    # Nivel NAO e enviado: ele e atribuido por um admin (POST /admin/users).
    payload = json.dumps({
        "email": email,
        "nome": nome,
        "storage_state": state,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{SERVER_URL}/api/token/upload",
        data=payload,
        headers={"X-Onboarding-Token": ONBOARDING_TOKEN, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        print("\n[OK] Token enviado com sucesso!")
        print(f"     Usuario: {data.get('email', email)}")
        print(f"     Cookies: {data.get('cookies', '?')}")
        if data.get("aviso"):
            print(f"\n  {data['aviso']}")
        limpar_perfil_local(profile)
        print("\nNo Claude, use o conector MCP (login Google) assim que o admin ativar.")
    except urllib.error.HTTPError as e:
        print(f"\n[ERRO] Servidor retornou {e.code}: {e.read().decode()}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERRO] Falha ao enviar: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Conector NotebookLM")
    parser.add_argument("--email", required=True, help="Seu email Google do NotebookLM")
    parser.add_argument("--nome", default="", help="Seu nome completo")
    parser.add_argument("--profile", default=None,
                        help="Nome do perfil local (padrao: derivado do email)")
    args = parser.parse_args()

    profile = nome_de_perfil(args.profile or args.email.split("@")[0])

    print("=" * 55)
    print(" Conector NotebookLM")
    print("=" * 55)

    run_login(profile)
    print("[2/3] Lendo token capturado...")
    state = load_storage_state(profile)
    upload(args.email, args.nome, state, profile)


if __name__ == "__main__":
    main()
