# -*- coding: utf-8 -*-
"""
Cofre local do token de administrador.

Guarda o token de administrador cifrado com uma senha que so o dono conhece,
para que ele nao precise ser colado a cada abertura nem anotado em outro lugar.
A senha nunca sai da maquina e nao vai para o servidor: nao ha login remoto
envolvido, so um cofre.

--------------------------------------------------------------------------
ONDE O COFRE PODE FICAR
--------------------------------------------------------------------------

Tres lugares, procurados nesta ordem:

1. A raiz de uma unidade removivel plugada — o pendrive. O programa fica
   instalado na maquina e a chave anda com quem a carrega.
2. Ao lado do proprio programa, para quando o programa TAMBEM esta no pendrive.
3. Na pasta do usuario, o padrao de quem usa sempre o mesmo computador.

A procura e por TIPO de unidade, nunca por um caminho memorizado: a letra de um
pendrive muda de maquina para maquina e de porta para porta, entao uma letra
guardada em configuracao passa a apontar para o lugar errado assim que o
pendrive troca de posicao. Perguntar ao sistema quais unidades sao removiveis
funciona em qualquer porta e em qualquer maquina.

--------------------------------------------------------------------------
O MODELO: SENHA, NAO ENDERECO DE REDE
--------------------------------------------------------------------------

A garantia de que a credencial nao serve noutra maquina vem da senha, nao do
endereco de rede. Restricao por IP nao se aplica neste ambiente:

1. Atras de um proxy reverso, o servidor recebe o IP do proxy, nao o do cliente.

2. `X-Forwarded-For` e um cabecalho enviado PELO cliente, entao quem quisesse
   burlar escolheria o proprio valor.

3. IP muda: rede nova, VPN ou DHCP derrubariam o acesso sem motivo aparente.

O arquivo do cofre sozinho nao serve, porque a senha nao esta nele.

--------------------------------------------------------------------------
O QUE ISTO PROTEGE, E O QUE NAO
--------------------------------------------------------------------------

PROTEGE de quem copiar o arquivo: sem a senha, o conteudo e inutil. scrypt com
custo alto torna forca bruta cara mesmo para senha mediana.

NAO PROTEGE de quem controla a maquina enquanto o painel esta aberto: com o
cofre destrancado, o token esta em memoria. Nenhum cofre local resolve isso —
quem tem a maquina, tem a sessao.

O pendrive e posse de um ARQUIVO, nao de um dispositivo: nada impede que o
arquivo seja copiado para outro lugar. O que ele garante e que a maquina nao
fica com credencial depois que o pendrive sai — nao que a credencial seja
inseparavel daquele pendrive. Quem protege de fato continua sendo a senha.
"""
import base64
import ctypes
import json
import os
import pathlib
import secrets
import string
import sys

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

NOME_ARQUIVO = "admin.cofre"

_DRIVE_REMOVIVEL = 2  # DRIVE_REMOVABLE, do GetDriveTypeW da API do Windows


def _pasta_do_programa() -> pathlib.Path:
    """
    Onde o executavel esta — que pode ser um pendrive.

    Em bundle --onefile do PyInstaller, __file__ aponta para uma pasta temporaria
    que e apagada ao sair. So sys.executable da o caminho real do .exe.
    """
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).parent
    return pathlib.Path(__file__).parent


def unidades_removiveis() -> list[pathlib.Path]:
    """
    Unidades removiveis montadas agora.

    No Windows a pergunta vai ao proprio sistema, que classifica cada unidade.
    Fora dele, sao consultados os pontos de montagem usados para midia externa.
    """
    achadas: list[pathlib.Path] = []

    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        mascara = k32.GetLogicalDrives()
        for i, letra in enumerate(string.ascii_uppercase):
            if not mascara & (1 << i):
                continue
            raiz = f"{letra}:" + chr(92)
            if k32.GetDriveTypeW(ctypes.c_wchar_p(raiz)) == _DRIVE_REMOVIVEL:
                achadas.append(pathlib.Path(raiz))
        return achadas

    for base, sufixo in (("/media", "*"), ("/media", "*/*"),
                         ("/run/media", "*/*"), ("/Volumes", "*")):
        try:
            achadas.extend(p for p in pathlib.Path(base).glob(sufixo)
                           if p.is_dir() and os.access(p, os.W_OK))
        except OSError:
            pass
    return achadas


def _em_unidade_removivel(alvo: pathlib.Path) -> bool:
    try:
        alvo = alvo.resolve()
    except OSError:
        return False
    for u in unidades_removiveis():
        try:
            u = u.resolve()
        except OSError:
            continue
        if alvo == u or u in alvo.parents:
            return True
    return False


PORTATIL = _pasta_do_programa() / NOME_ARQUIVO
LOCAL = pathlib.Path.home() / ".notebooklm" / NOME_ARQUIVO


def destinos_de_pendrive() -> list[pathlib.Path]:
    """
    Onde o cofre pode ser gravado no modo pendrive, em ordem de preferencia.

    Vazia quando nao ha unidade removivel plugada. Com mais de um item, a
    escolha e de quem esta na frente da tela: o programa nao tem como saber
    qual dos pendrives e o certo.
    """
    pasta = _pasta_do_programa()
    if _em_unidade_removivel(pasta):
        return [pasta / NOME_ARQUIVO]
    return [u / NOME_ARQUIVO for u in unidades_removiveis()]


def caminho() -> pathlib.Path | None:
    """
    O cofre em uso, ou None se nao ha nenhum.

    O pendrive tem precedencia: plugado, e ele que manda. Retirado, a maquina
    volta ao cofre local, se existir um — e ter os dois e ter duas credenciais
    independentes, o que `apagar_local()` desfaz.
    """
    for u in unidades_removiveis():
        alvo = u / NOME_ARQUIVO
        if alvo.exists():
            return alvo
    if PORTATIL.exists():
        return PORTATIL
    if LOCAL.exists():
        return LOCAL
    return None


def e_portatil() -> bool:
    """O cofre em uso esta fora da pasta do usuario deste computador."""
    atual = caminho()
    return atual is not None and atual != LOCAL


def onde_esta() -> str:
    """Frase curta sobre a origem do cofre em uso, para mostrar na tela."""
    atual = caminho()
    if atual is None:
        return "nenhum cofre encontrado"
    if atual == LOCAL:
        return "chave guardada neste computador"
    if _em_unidade_removivel(atual):
        return f"chave lida do pendrive ({atual.drive or atual.parent})"
    return "chave lida da pasta do programa"


def dentro_de_repositorio(destino: pathlib.Path | None = None) -> bool:
    """
    Um cofre gravado em pasta versionada acompanharia o repositorio, cifrado e
    tudo, protegido apenas pela forca da senha escolhida. Detectar o `.git`
    permite avisar antes de gravar.
    """
    pasta = (destino or PORTATIL).parent
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


def gravar(senha: str, servidor: str, token: str,
           destino: pathlib.Path | None = None) -> pathlib.Path:
    """
    Cria ou substitui o cofre. Sal novo a cada gravacao.

    `destino` vem de destinos_de_pendrive() no modo pendrive. Sem ele, o cofre
    fica na pasta do usuario deste computador.
    """
    destino = destino or LOCAL
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
    """Apaga o cofre em uso. Nao mexe nos outros, se houver."""
    alvo = caminho()
    if alvo:
        alvo.unlink(missing_ok=True)


def tem_cofre_local() -> bool:
    """Ha um cofre na pasta do usuario, alem do que estiver no pendrive."""
    return LOCAL.exists()


def apagar_local() -> None:
    """
    Apaga o cofre deste computador.

    Depois de gravar no pendrive, e o que faz a maquina ficar de fato sem
    credencial quando o pendrive sai.
    """
    LOCAL.unlink(missing_ok=True)
