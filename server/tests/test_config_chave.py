"""
Validacao da NOTEBOOKLM_ENCRYPTION_KEY.

Motivados por uma falha real de deploy: a chave colada no painel perdeu o '='
final, e o servidor morreu no import do db.py com 40 linhas de traceback
terminando em `binascii.Error: Incorrect padding`. A causa — um caractere
comido na colagem — nao aparecia em lugar nenhum da saida.

A funcao e testada diretamente, sem recarregar config: config.py le
os.environ no import e ja foi importado pelo conftest.
"""
import base64

import pytest
from cryptography.fernet import Fernet

from config import _valida_chave_fernet


def test_chave_valida_passa():
    chave = Fernet.generate_key().decode()
    assert _valida_chave_fernet(chave) == chave


def test_chave_sem_o_igual_final_e_o_caso_do_deploy_real():
    """43 caracteres: comprimento nao multiplo de 4, que produz Incorrect padding."""
    chave = Fernet.generate_key().decode()
    assert chave.endswith("=")

    truncada = chave[:-1]
    assert len(truncada) == 43

    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet(truncada)

    msg = str(erro.value)
    assert "43 caracteres" in msg, "a mensagem precisa dizer o tamanho encontrado"
    assert "esperado 44" in msg
    assert "'=' final" in msg, "precisa apontar a causa provavel"
    assert "Fernet.generate_key" in msg, "precisa dizer como gerar outra"


def test_valor_curto_nao_sugere_o_igual_final():
    """
    Segundo deploy real: o campo tinha 24 caracteres. A primeira versao desta
    validacao mandou procurar o '=' faltando — palpite impossivel nesse tamanho,
    porque perder o '=' daria 43. A pista precisa caber no que foi encontrado.
    """
    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet("x" * 24)

    msg = str(erro.value)
    assert "24 caracteres" in msg
    assert "'='" not in msg, "nao pode sugerir o '=' final num valor de 24 caracteres"
    assert "outro valor" in msg, "precisa dizer que provavelmente e o campo errado"


def test_valor_com_simbolos_e_apontado_como_outro_segredo():
    """Uma senha de 24 caracteres com simbolos foi a suspeita no deploy real."""
    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet("S3nh@!MuitoF0rte#2026x%&")

    msg = str(erro.value)
    assert "simbolos" in msg
    assert "senha" in msg


def test_o_valor_recusado_nunca_aparece_na_mensagem():
    """
    A mensagem vai para o log do container. Ecoar o conteudo trocaria um erro de
    configuracao por um vazamento: o campo errado costuma ter um segredo de
    verdade dentro.
    """
    segredo = "S3nh@-do-banco-de-producao!"
    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet(segredo)

    msg = str(erro.value)
    assert segredo not in msg
    for pedaco in ("S3nh@", "producao", "banco"):
        assert pedaco not in msg, f"a mensagem vazou '{pedaco}'"


def test_valor_vazio_diz_que_esta_vazio():
    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet("   ")
    assert "vazio" in str(erro.value)


def test_a_pista_muda_conforme_o_tamanho():
    """As duas causas sao diferentes e nao podem receber a mesma orientacao."""
    chave = Fernet.generate_key().decode()

    with pytest.raises(RuntimeError) as quase:
        _valida_chave_fernet(chave[:-1])          # 43 — perdeu o '='
    with pytest.raises(RuntimeError) as longe:
        _valida_chave_fernet(chave[:20])          # 20 — outro valor

    assert str(quase.value) != str(longe.value)
    assert "'='" in str(quase.value)
    assert "'='" not in str(longe.value)


def test_placeholder_do_env_example_e_recusado():
    with pytest.raises(RuntimeError):
        _valida_chave_fernet("gere-uma-chave-fernet-e-mantenha-so-aqui")


def test_aspas_e_espaco_em_volta_sao_tolerados():
    """
    Erro de colagem comum. Sem a limpeza, uma chave CERTA falharia por causa de
    um caractere invisivel — e a mensagem de erro apontaria para o lugar errado.
    """
    chave = Fernet.generate_key().decode()
    for sujo in (f'"{chave}"', f"'{chave}'", f"  {chave}  ", f"{chave}\n"):
        assert _valida_chave_fernet(sujo) == chave


def test_base64_valido_mas_com_bytes_de_menos():
    """16 bytes em vez de 32: decodifica, mas o Fernet recusaria depois."""
    curta = base64.urlsafe_b64encode(b"x" * 16).decode()

    with pytest.raises(RuntimeError) as erro:
        _valida_chave_fernet(curta)

    assert "16 bytes" in str(erro.value)
    assert "32" in str(erro.value)


def test_a_chave_validada_e_aceita_pelo_fernet():
    """
    O teste que fecha o circulo: o que passa aqui tem que servir para o db.py.
    Sem ele, a validacao poderia divergir do que o Fernet realmente exige.
    """
    chave = _valida_chave_fernet(Fernet.generate_key().decode())
    Fernet(chave.encode())
