# -*- coding: utf-8 -*-
"""
Cofre local do token de administrador.

O painel precisava do token colado a cada abertura. Isso empurra para o pior dos
mundos: ou a pessoa guarda a chave num bloco de notas, ou desiste de usar.

Aqui o token e guardado cifrado com uma senha que so o dono conhece. A senha
nunca sai da maquina e nao vai para o servidor — nao ha login remoto envolvido,
so um cofre.

--------------------------------------------------------------------------
POR QUE NAO AMARRAR AO IP DA MAQUINA
--------------------------------------------------------------------------

Foi a ideia inicial, e nao funciona neste ambiente:

1. O servidor nao ve o IP do cliente. Atras do proxy do EasyPanel, toda
   requisicao chega como o IP do proxy (10.11.0.11 nos logs). Nao ha como
   distinguir a maquina do doutor de qualquer outra.

2. Mesmo que visse, `X-Forwarded-For` e enviado PELO cliente. Quem quisesse
   burlar escolheria o proprio IP — verificado: um XFF forjado foi aceito.

3. IP muda. Rede nova, VPN, DHCP, e o acesso morre sem motivo aparente.

O que a ideia queria de fato — "a credencial nao deve funcionar noutra maquina" —
esta atendido: o arquivo do cofre sozinho nao serve, porque a senha nao esta nele.

--------------------------------------------------------------------------
O QUE ISTO PROTEGE, E O QUE NAO
--------------------------------------------------------------------------

PROTEGE de quem copiar o arquivo: sem a senha, o conteudo e inutil. scrypt com
custo alto torna forca bruta cara mesmo para senha mediana.

NAO PROTEGE de quem controla a maquina enquanto o painel esta aberto: com o
cofre destrancado, o token esta em memoria. Nenhum cofre local resolve isso —
quem tem a maquina, tem a sessao.
"""
import base64
import json
import os
import pathlib
import secrets
import sys

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

NOME_ARQUIVO = "admin.cofre"


def _pasta_do_programa() -> pathlib.Path:
    """
    Onde o executavel esta — que pode ser um pendrive.

    Em bundle --onefile do PyInstaller, __file__ aponta para uma pasta temporaria
    que e apagada ao sair. So sys.executable da o caminho real do .exe.
    """
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).parent
    return pathlib.Path(__file__).parent


PORTATIL = _pasta_do_programa() / NOME_ARQUIVO
LOCAL = pathlib.Path.home() / ".notebooklm" / NOME_ARQUIVO


def caminho() -> pathlib.Path | None:
    """
    O cofre em uso, ou None se nao ha nenhum.

    O portatil tem precedencia: se o pendrive esta plugado, ele manda. Assim o
    doutor pluga em qualquer maquina e entra com a senha; ao tirar o pendrive,
    a maquina volta a nao ter credencial nenhuma.
    """
    if PORTATIL.exists():
        return PORTATIL
    if LOCAL.exists():
        return LOCAL
    return None


def e_portatil() -> bool:
    return caminho() == PORTATIL


def dentro_de_repositorio() -> bool:
    """
    O modo portatil grava ao lado do .exe. Se o .exe estiver dentro de um
    repositorio git, o cofre nasce versionavel — e um `git add -A` levaria a
    chave de administrador para o servidor de codigo.

    O caso e concreto, nao hipotetico: com o .exe em client/, dentro do
    repositorio, o cofre nasce ali do lado e passa a ser candidato a `git add`.

    Cifrado nao resolve: um repositorio entregue a terceiros carregaria a chave
    de quem o criou, protegida apenas pela forca da senha escolhida.
    """
    pasta = _pasta_do_programa()
    for p in [pasta, *pasta.parents]:
        if (p / ".git").exists():
            return True
    return False

# n=2**15 leva ~100ms por tentativa nesta classe de maquina. Imperceptivel para
# quem digita a senha certa; caro o bastante para inviabilizar varredura de
# dicionario sobre o arquivo roubado.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1


class SenhaErrada(Exception):
    pass


def existe() -> bool:
    return caminho() is not None


def _chave(senha: str, sal: bytes) -> bytes:
    kdf = Scrypt(salt=sal, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(senha.encode("utf-8")))


def gravar(senha: str, servidor: str, token: str, portatil: bool = False) -> pathlib.Path:
    """
    Cria ou substitui o cofre. Sal novo a cada gravacao.

    portatil=True grava ao lado do executavel — tipicamente um pendrive. O
    arquivo viaja junto e nao deixa credencial na maquina emprestada.
    """
    destino = PORTATIL if portatil else LOCAL
    sal = secrets.token_bytes(16)
    conteudo = json.dumps({"servidor": servidor, "token": token}).encode("utf-8")
    cifrado = Fernet(_chave(senha, sal)).encrypt(conteudo)

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(json.dumps({
        "versao": 1,
        "sal": base64.b64encode(sal).decode(),
        "dados": cifrado.decode(),
    }).encode("utf-8"))

    # Em POSIX, so o dono le. No Windows nao tem efeito — la a protecao e a ACL
    # herdada do perfil do usuario, o que ja e o comportamento padrao.
    try:
        os.chmod(destino, 0o600)
    except OSError:
        pass
    return destino


def abrir(senha: str) -> tuple[str, str]:
    """Devolve (servidor, token). Levanta SenhaErrada se nao destrancar."""
    alvo = caminho()
    if alvo is None:
        raise FileNotFoundError("Nenhum cofre encontrado.")
    bruto = json.loads(alvo.read_bytes().decode("utf-8"))
    sal = base64.b64decode(bruto["sal"])
    try:
        aberto = Fernet(_chave(senha, sal)).decrypt(bruto["dados"].encode())
    except InvalidToken:
        # Fernet autentica antes de decifrar: senha errada e arquivo adulterado
        # produzem o mesmo erro, e nao ha como distinguir — nem se deve.
        raise SenhaErrada("Senha incorreta.") from None
    d = json.loads(aberto.decode("utf-8"))
    return d["servidor"], d["token"]


def apagar() -> None:
    """Apaga o cofre em uso. Nao mexe no outro, se houver."""
    alvo = caminho()
    if alvo:
        alvo.unlink(missing_ok=True)
