"""
Verifica que a imutabilidade do audit_log e do access_log existe DE FATO no banco.

A garantia de auditoria e o que sustenta o argumento de sigilo profissional: sem
ela, "toda pergunta fica registrada" e promessa de codigo, nao propriedade do
sistema. Codigo se refatora; trigger no banco recusa mesmo que o app peca.

Este script prova, ou desmente, rodando de verdade contra o banco.

Uso:
    set DATABASE_URL=postgres://user:senha@host:5432/notebooklm
    python server/db/verifica_auditoria.py

    --com-truncate   inclui o teste de TRUNCATE (ver aviso abaixo)

Nao deixa rastro: tudo roda numa transacao com savepoints e termina em ROLLBACK.
Nem mesmo a linha de teste inserida sobrevive.

AVISO sobre --com-truncate: TRUNCATE pega ACCESS EXCLUSIVE na tabela. E
transacional (o rollback desfaz), mas bloqueia leitores enquanto roda. Em banco
recem-criado nao ha problema; em producao com uso, rode fora do horario.
"""
import os
import sys
from urllib.parse import urlparse

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERRO: defina a variavel de ambiente DATABASE_URL")
    sys.exit(1)

COM_TRUNCATE = "--com-truncate" in sys.argv

TABELAS = ["audit_log", "access_log"]

# Uma linha minima por tabela, so com colunas que existem em ambas as versoes do
# schema. O conteudo e irrelevante: o que se testa e o que acontece DEPOIS.
INSERTS = {
    "audit_log":  ("INSERT INTO notebooklm.audit_log (email, notebook_id, pergunta, resposta) "
                   "VALUES ('__verificacao__', '__teste__', 'x', 'y') RETURNING id"),
    "access_log": ("INSERT INTO notebooklm.access_log (evento, identity_email, detalhe) "
                   "VALUES ('verificacao', '__verificacao__', 'teste de imutabilidade') RETURNING id"),
}

# Coluna comum a alterar no teste de UPDATE. Nao usar a chave primaria: o trigger
# dispararia igual, mas um erro de constraint seria indistinguivel da recusa que
# se quer provar — o teste passaria pelo motivo errado.
COLUNA_UPDATE = {"audit_log": "resposta", "access_log": "detalhe"}


def _db_params() -> dict:
    u = urlparse(DATABASE_URL)
    params = {
        "host": u.hostname,
        "port": u.port or 5432,
        "dbname": u.path.lstrip("/"),
        "user": u.username,
        "password": u.password,
    }
    query = u.query or ""
    if "sslmode=disable" in query:
        params["sslmode"] = "disable"
    elif "sslmode=" not in query:
        params["sslmode"] = "require"
    # Sem isto, host errado nao da erro: fica pendurado no timeout default do
    # psycopg, que e longo, sem imprimir nada. Quem roda acha que travou.
    params["connect_timeout"] = 10
    return {k: v for k, v in params.items() if v is not None}


resultados = []


def checa(nome: str, ok: bool, detalhe: str = "") -> None:
    resultados.append((nome, ok, detalhe))
    marca = "PASSOU" if ok else "FALHOU"
    print(f"  [{marca}] {nome}" + (f" — {detalhe}" if detalhe else ""))


def espera_recusa(cur, sql: str, nome: str, params=None) -> None:
    """Roda `sql` esperando que o banco RECUSE. Passa se levantar excecao."""
    cur.execute("SAVEPOINT sp")
    try:
        cur.execute(sql, params or ())
    except psycopg.errors.RaiseException as e:
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        msg = str(e).strip().split("\n")[0]
        checa(nome, True, msg[:80])
        return
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT sp")
        checa(nome, True, f"recusado ({type(e).__name__})")
        return
    cur.execute("ROLLBACK TO SAVEPOINT sp")
    checa(nome, False, "o banco ACEITOU a operacao")


def conecta():
    """
    Conecta traduzindo a falha em instrucao. Um traceback de psycopg nao ajuda
    quem nunca viu este codigo — e essa e exatamente a pessoa que vai rodar isto.
    """
    p = _db_params()
    try:
        return psycopg.connect(**p)
    except psycopg.OperationalError as e:
        msg = str(e).lower()
        print(f"\nNao consegui conectar em {p.get('host')}:{p.get('port')}, "
              f"banco '{p.get('dbname')}', usuario '{p.get('user')}'.\n")
        if "password authentication failed" in msg:
            print("  Causa: senha recusada.")
            print("  A rede, o host e a porta estao certos — so a credencial nao bate.")
        elif "does not exist" in msg and "database" in msg:
            print(f"  Causa: o banco '{p.get('dbname')}' nao existe neste servidor.")
            print("  Confira o nome. Atencao a espacos: eles sobrevivem ao parse da URL,")
            print("  entao 'Novo banco' e 'Novobanco' sao bancos diferentes.")
        elif "timeout" in msg or "refused" in msg or "could not translate" in msg:
            print("  Causa: nao houve resposta na porta.")
            print("  Servidor fora do ar, porta fechada, ou host errado.")
        else:
            print(f"  Erro do driver: {str(e).strip().splitlines()[0]}")
        print("\n  DATABASE_URL esperada:")
        print("    postgres://usuario:senha@host:porta/banco?sslmode=disable")
        sys.exit(2)


def main() -> int:
    print(f"Verificando imutabilidade em {_db_params().get('host')}\n")
    conn = conecta()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── 1. Os triggers existem? ──────────────────────────────────────────
        print("Triggers registrados no catalogo:")
        for t in TABELAS:
            cur.execute(
                "SELECT tgname, tgtype FROM pg_trigger tg "
                "JOIN pg_class c ON c.oid = tg.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'notebooklm' AND c.relname = %s AND NOT tg.tgisinternal",
                (t,),
            )
            achados = cur.fetchall()
            checa(f"{t}: trigger presente", bool(achados),
                  ", ".join(r[0] for r in achados) or "NENHUM")
        print()

        # ── 2. INSERT funciona, UPDATE e DELETE sao recusados ────────────────
        for t in TABELAS:
            print(f"{t}:")
            cur.execute(INSERTS[t])
            rid = cur.fetchone()[0]
            checa(f"{t}: INSERT aceito", True, f"id={rid}")

            col = COLUNA_UPDATE[t]
            espera_recusa(cur,
                          f"UPDATE notebooklm.{t} SET {col} = 'alterado' WHERE id = %s",
                          f"{t}: UPDATE recusado", (rid,))
            espera_recusa(cur,
                          f"DELETE FROM notebooklm.{t} WHERE id = %s",
                          f"{t}: DELETE recusado", (rid,))

            if COM_TRUNCATE:
                espera_recusa(cur, f"TRUNCATE TABLE notebooklm.{t}",
                              f"{t}: TRUNCATE recusado")
            print()

    finally:
        conn.rollback()   # nada do que foi inserido sobrevive
        conn.close()

    # ── Veredito ─────────────────────────────────────────────────────────────
    falhas = [n for n, ok, _ in resultados if not ok]
    print("-" * 62)
    if not falhas:
        print(f"OK: {len(resultados)} verificacoes passaram. Nada persistido (rollback).")
        if not COM_TRUNCATE:
            print("\nNao testado: TRUNCATE. Rode com --com-truncate para incluir.")
            print("O trigger e BEFORE UPDATE OR DELETE — TRUNCATE e evento separado")
            print("e provavelmente NAO esta coberto. Vale confirmar.")
        return 0

    print(f"FALHOU: {len(falhas)} de {len(resultados)} verificacoes.")
    for f in falhas:
        print(f"  - {f}")
    print("\nA imutabilidade do log NAO esta garantida pelo banco.")
    print("Reaplique o schema (server/db/apply_schema.py) e rode de novo.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
