# -*- coding: utf-8 -*-
"""
Gera o executavel do painel de administracao.

    pip install pyinstaller
    python build_exe.py

Sai em dist/Administrar Acessos.exe — ~14 MB, autonomo: roda em maquina SEM
Python instalado. Verificado abrindo com o PATH sem nenhum interpretador.

--------------------------------------------------------------------------
O SMARTSCREEN BLOQUEIA ESTE EXECUTAVEL — E ESTA CERTO
--------------------------------------------------------------------------

Medido em 17/08/2026, no Windows 11:

    (Get-AuthenticodeSignature 'Administrar Acessos.exe').Status  ->  NotSigned
    (Get-AuthenticodeSignature (Get-Command python).Source).Status ->  Valid

O Windows barra executavel sem assinatura e sem reputacao, com a tela "O Windows
protegeu o seu PC". Nao e o Defender: verificado que o arquivo nao vai para
quarentena, nao tem Mark-of-the-Web e nao gera deteccao. E reputacao, so.

Nao ha truque de build que resolva. As saidas reais sao tres:

1. Certificado de assinatura de codigo. A solucao de verdade, e um custo
   recorrente com exigencia de CNPJ. Certificado OV ainda acumula reputacao por
   um tempo antes de o aviso sumir; so o EV da confianca imediata.
2. "Mais informacoes -> Executar assim mesmo", uma vez por maquina. Funciona,
   mas treina o usuario a passar por cima de aviso de seguranca.
3. O .bat com Python instalado — que chama o python.exe, assinado, e nao gera
   aviso nenhum.

Por isso o ACESSOS.md documenta o .bat como caminho principal e este exe como
alternativa. O exe continua util para pendrive circulando entre maquinas, onde
nao da para exigir Python.

Se um dia houver certificado, nada aqui muda: assine o artefato depois do build
   signtool sign /fd SHA256 /tr <timestamp> /td SHA256 "dist/Administrar Acessos.exe"

--------------------------------------------------------------------------
POR QUE SO O PAINEL, E NAO O CONECTOR
--------------------------------------------------------------------------

O admin.pyw usa apenas biblioteca padrao (tkinter + urllib), entao o PyInstaller
resolve tudo sozinho.

O conector (app.pyw -> connect.py) nao: ele precisa do Playwright e de um
Chromium de ~150 MB, que nao cabe num executavel e continua sendo baixado na
primeira execucao de qualquer jeito. Empacota-lo daria um exe grande que ainda
assim exigiria download — pouco ganho, bastante fragilidade (o bundling do
driver do Playwright pelo PyInstaller e conhecidamente sensivel a versao).

Para o conector, o caminho e o "Conectar ao NotebookLM.bat" com Python
instalado na maquina de onboarding. Como e UMA maquina, nao a de cada advogado,
o custo e pago uma vez.

Se um dia valer empacotar o conector: o CLI notebooklm tem entry point em
`notebooklm.notebooklm_cli:main`, entao da para o exe reinvocar a si mesmo com
uma flag em vez de procurar o binario no PATH.
"""
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).parent
ORIGEM = AQUI / "admin.pyw"
NOME = "Administrar Acessos"


def main() -> int:
    if not ORIGEM.exists():
        print(f"ERRO: {ORIGEM} nao encontrado.")
        return 1

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERRO: PyInstaller nao instalado.\n\n    pip install pyinstaller")
        return 1

    # O PyInstaller nao aceita .pyw como entrada em todas as versoes; copiar
    # para .py evita a diferenca de comportamento entre elas.
    temp = AQUI / "_build_admin.py"
    shutil.copy(ORIGEM, temp)

    try:
        r = subprocess.run([
            sys.executable, "-m", "PyInstaller",
            "--onefile",       # um arquivo so, para copiar e usar
            "--windowed",      # sem console preto atras da janela
            "--clean",
            "--name", NOME,
            "--distpath", str(AQUI / "dist"),
            "--workpath", str(AQUI / "build"),
            "--specpath", str(AQUI / "build"),
            str(temp),
        ])
    finally:
        temp.unlink(missing_ok=True)

    if r.returncode != 0:
        return r.returncode

    exe = AQUI / "dist" / f"{NOME}.exe"
    if exe.exists():
        print(f"\nOK: {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
        print("\nConfira antes de distribuir: abra numa maquina sem Python.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
