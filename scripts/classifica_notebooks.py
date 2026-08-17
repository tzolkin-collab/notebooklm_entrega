"""
Classifica os notebooks da conta por area (juridico/financeiro/comercial)
e alimenta a tabela notebooklm.notebooks do servidor.

Fluxo (2 passos, com revisao humana no meio):

  1. Gerar a proposta de classificacao (roda na maquina que tem o profile):
       python scripts/classifica_notebooks.py --gerar --profile default
     -> escreve classificacao_notebooks.csv (id, titulo, area_sugerida)

  2. Um gestor revisa o CSV (ajusta a coluna `area` onde a regra errou) e envia:
       set NOTEBOOKLM_ADMIN_TOKEN=<token Bearer de um usuário admin>
       python scripts/classifica_notebooks.py --enviar
     -> POST /api/admin/notebooks-classificacao em lotes de 50
       (o token admin sai de: python server/db/gen_token.py --email <admin>)

Regras de sugestao (ordem):
  - titulo contendo termo financeiro (financeiro, fatura, cobranca, pagamento,
    contabil, fiscal, imposto)                                  -> financeiro
  - titulo de diretoria/estrategia/comercial (diretoria, estrategic, comercial,
    marketing, prospec)                                          -> comercial
  - resto (CONT -, CONSULTA, numero CNJ, LGPD, teses etc.)      -> juridico
"""
import argparse
import asyncio
import csv
import json
import os
import pathlib
import re
import sys
import unicodedata
import urllib.request

SERVER_URL = os.getenv("NOTEBOOKLM_SERVER_URL", "").rstrip("/")
if not SERVER_URL:
    sys.exit(
        "ERRO: defina a variavel de ambiente NOTEBOOKLM_SERVER_URL com a URL do "
        "servidor do escritorio (ex.: https://<host>)."
    )

CSV_PATH = pathlib.Path(__file__).parent / "classificacao_notebooks.csv"

FINANCEIRO = re.compile(r"financeir|fatur|cobranc|pagament|contabil|fiscal|imposto")
COMERCIAL = re.compile(r"diretoria|estrategic|comercial|marketing|prospec")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def sugerir_area(titulo: str) -> str:
    t = _norm(titulo)
    if FINANCEIRO.search(t):
        return "financeiro"
    if COMERCIAL.search(t):
        return "comercial"
    return "juridico"


async def gerar(profile: str) -> None:
    from notebooklm import NotebookLMClient

    storage = pathlib.Path.home() / ".notebooklm" / "profiles" / profile / "storage_state.json"
    if not storage.exists():
        sys.exit(f"ERRO: profile '{profile}' nao encontrado em {storage}")

    async with NotebookLMClient.from_storage(path=str(storage)) as client:
        notebooks = await client.notebooks.list()

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "titulo", "area"])
        for nb in notebooks:
            w.writerow([nb.id, nb.title, sugerir_area(nb.title or "")])

    print(f"OK: {len(notebooks)} notebooks classificados em {CSV_PATH}")
    print("Revise a coluna 'area' antes de enviar (--enviar).")


def enviar() -> None:
    admin_token = os.getenv("NOTEBOOKLM_ADMIN_TOKEN", "")
    if not admin_token:
        sys.exit("ERRO: defina NOTEBOOKLM_ADMIN_TOKEN (token Bearer de um admin) no ambiente.")
    if not CSV_PATH.exists():
        sys.exit(f"ERRO: {CSV_PATH} nao existe. Rode --gerar primeiro.")

    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]

    invalidas = [r for r in rows if r["area"] not in ("juridico", "financeiro", "comercial")]
    if invalidas:
        sys.exit(f"ERRO: {len(invalidas)} linhas com area invalida (ex: {invalidas[0]})")

    total = 0
    for i in range(0, len(rows), 50):
        lote = rows[i:i + 50]
        body = json.dumps({"notebooks": lote}).encode()
        req = urllib.request.Request(
            f"{SERVER_URL}/api/admin/notebooks-classificacao",
            data=body,
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
        total += result.get("gravados", 0)
        print(f"lote {i // 50 + 1}: {result}")

    print(f"OK: {total}/{len(rows)} notebooks gravados no servidor.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--gerar", action="store_true", help="lista notebooks e gera o CSV de classificacao")
    g.add_argument("--enviar", action="store_true", help="envia o CSV revisado para o servidor")
    ap.add_argument("--profile", default="default", help="profile local do notebooklm (para --gerar)")
    args = ap.parse_args()

    if args.gerar:
        asyncio.run(gerar(args.profile))
    else:
        enviar()
