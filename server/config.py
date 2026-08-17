import base64
import binascii
import os
from dotenv import load_dotenv

load_dotenv()


_COMO_GERAR = (
    'Gere uma nova com:\n'
    '  python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


_ALFABETO_B64 = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
)


def _pista_do_conteudo(chave: str) -> str:
    """
    Diz o QUE parece estar no campo, sem revelar o valor.

    O conteudo nunca e impresso: se o campo tem uma senha — que foi a suspeita
    num deploy real — ecoa-la no log do container trocaria um erro de
    configuracao por um vazamento de credencial.

    Reportar so as classes de caractere basta para o operador reconhecer o que
    colou: chave Fernet nao tem simbolo nenhum alem de '-', '_' e '='.
    """
    fora = {c for c in chave if c not in _ALFABETO_B64}
    if not fora:
        return ""
    tipos = []
    if any(c.isspace() for c in fora):
        tipos.append("espaco ou quebra de linha")
    if any(not c.isspace() and not c.isalnum() for c in fora):
        tipos.append("simbolos")
    if any(c.isalnum() for c in fora):
        tipos.append("caracteres acentuados")
    return (
        f"O valor contem {' e '.join(tipos)}, que nao existem numa chave Fernet "
        f"(so letras, numeros, '-', '_' e '='). Parece ser outro tipo de "
        f"segredo — uma senha, por exemplo."
    )


def _pista_do_tamanho(n: int) -> str:
    """
    A pista precisa caber no tamanho encontrado.

    A primeira versao desta validacao sugeria "confira se o '=' final
    sobreviveu" para QUALQUER tamanho errado. Num deploy real o valor tinha 24
    caracteres, e a mensagem mandou o operador procurar um caractere faltando —
    quando o problema era outro: o campo tinha um valor que nem chave era.

    Palpite confiante e errado custa mais tempo do que nenhum palpite.
    """
    if n == 0:
        return "O valor esta vazio — a variavel existe mas nao foi preenchida."
    if n == 43:
        return (
            "Falta exatamente 1 caractere, e quase sempre e o '=' final. Painel "
            "que trata a variavel como KEY=VALUE as vezes come esse '='; colar "
            "entre aspas costuma resolver."
        )
    if n < 30 or n > 60:
        # Sem exemplos aqui de proposito: quando o valor tem simbolos, a pista
        # de conteudo ja disse que parece senha, e repetir polui a linha do log.
        return (
            f"{n} caracteres esta longe dos 44 de uma chave Fernet — "
            f"provavelmente nao e a chave, e sim outro valor no campo."
        )
    return (
        "O tamanho esta perto do esperado: confira se o valor foi colado "
        "inteiro, sem quebra de linha no meio e sem caractere a mais."
    )


def _valida_chave_fernet(bruta: str) -> str:
    """
    Confere que a chave e mesmo uma chave Fernet antes que o db.py a use.

    Sem isto, uma chave malformada estoura no `Fernet(...)` do topo do db.py —
    durante o import, sob o uvicorn — e o operador recebe 40 linhas de traceback
    terminando em `binascii.Error: Incorrect padding`. A causa real (perdeu o
    '=' final ao colar no painel) nao aparece em lugar nenhum.

    Uma chave Fernet e o base64 url-safe de 32 bytes: 44 caracteres, o ultimo
    sempre '='. Painel que trata a variavel como KEY=VALUE as vezes come esse
    '=' final, e o resultado tem 43 caracteres — comprimento que nao e multiplo
    de 4, exatamente o que produz "Incorrect padding".
    """
    chave = bruta.strip().strip('"').strip("'")

    try:
        bytes_ = base64.urlsafe_b64decode(chave)
    except (binascii.Error, ValueError):
        raise RuntimeError(
            "\n".join(filter(None, [
                f"NOTEBOOKLM_ENCRYPTION_KEY nao e uma chave Fernet valida "
                f"(tem {len(chave)} caracteres, esperado 44).",
                _pista_do_conteudo(chave),
                _pista_do_tamanho(len(chave)),
                _COMO_GERAR,
            ]))
        ) from None

    if len(bytes_) != 32:
        raise RuntimeError(
            f"NOTEBOOKLM_ENCRYPTION_KEY decodifica para {len(bytes_)} bytes, "
            f"mas o Fernet exige exatamente 32.\n"
            f"{_pista_do_tamanho(len(chave))}\n"
            f"{_COMO_GERAR}"
        )

    # Devolve ja limpa: aspas e espaco em volta sao erro de colagem comum, e
    # deixar passar faria a chave "certa" falhar por um caractere invisivel.
    return chave

# DEPRECATED: a connector key compartilhada NAO autoriza mais /token/upload —
# foi substituida por tokens de onboarding por-usuario (POST /admin/onboarding-token).
# Mantida opcional só para compatibilidade; pode ser removida do ambiente.
API_KEY          = os.getenv("NOTEBOOKLM_CONNECTOR_API_KEY")
ENCRYPTION_KEY   = _valida_chave_fernet(os.environ["NOTEBOOKLM_ENCRYPTION_KEY"])
DATABASE_URL     = os.environ["DATABASE_URL"]
HOST             = os.getenv("HOST", "0.0.0.0")
PORT             = int(os.getenv("PORT", "80"))

# OAuth (conector MCP do Claude)
# Obrigatoria e sem default: o GoogleProvider monta o redirect_uri como
# PUBLIC_URL + "/auth/callback". Um default apontando para outro deploy faria o
# login da equipe passar silenciosamente por um servidor de terceiro — falha que
# nao levanta erro, so funciona errado. Melhor nao subir.
PUBLIC_URL                 = os.environ["PUBLIC_URL"]
GOOGLE_OAUTH_CLIENT_ID     = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

# ── Hardening opcional (defaults seguros e não-disruptivos) ──────────────────────
# Allowlist do OAuth do MCP. Vazio = sem restrição de front-door (o gate real
# continua sendo a ATIVAÇÃO por um admin). Preencha para negar contas fora do
# escritório antes mesmo do cadastro. Ex.:
#   NOTEBOOKLM_ALLOWED_DOMAINS=exemplo.com,outro-dominio.com
ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in os.getenv("NOTEBOOKLM_ALLOWED_DOMAINS", "").split(",") if d.strip()]
ALLOWED_EMAILS        = [e.strip().lower() for e in os.getenv("NOTEBOOKLM_ALLOWED_EMAILS", "").split(",") if e.strip()]

# Se true, uma pergunta só é respondida quando o registro no audit_log é gravado
# (LGPD: "toda pergunta gravada"). Default false preserva a disponibilidade atual
# (audit tolerante a falha). Ative em produção jurídica.
AUDIT_FAIL_CLOSED     = os.getenv("NOTEBOOKLM_AUDIT_FAIL_CLOSED", "false").lower() in ("1", "true", "yes")

# Rate limit por-usuário (email) nas tools do MCP, por minuto. Complementa o
# rate-limit por-IP da REST (o MCP não passa pelo slowapi). Contagem em memória,
# por-processo (o Dockerfile roda 1 worker uvicorn).
MCP_RATE_PER_MIN      = int(os.getenv("NOTEBOOKLM_MCP_RATE_PER_MIN", "30"))
