@echo off
rem Duplo clique aqui. Abre o painel de administracao de acessos.
rem
rem Este e o caminho principal do painel. O executavel ao lado faz o mesmo, mas
rem o SmartScreen do Windows bloqueia programa sem assinatura digital — ja o
rem python.exe e assinado, entao por aqui nao ha aviso nenhum.

cd /d "%~dp0"

rem ---------------------------------------------------------------------
rem 1. Existe Python?
rem ---------------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python nao encontrado neste computador.
    echo.
    echo  Instale em https://python.org/downloads
    echo  Marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

rem ---------------------------------------------------------------------
rem 2. Existem as dependencias?
rem
rem Esta verificacao roda com python.exe, que TEM console. Sem ela, o
rem `start "" pythonw` abaixo desanexa o processo e descarta o stderr: se
rem faltasse um componente, a janela nao abriria e nao apareceria mensagem
rem alguma. Duplo clique, nada acontece, nenhuma pista do motivo.
rem ---------------------------------------------------------------------
python -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Falta um componente: cryptography
    echo  E ele que mantem a sua chave de administrador cifrada em disco.
    echo.
    choice /c SN /n /m "  Instalar agora? [S/N] "
    if errorlevel 2 exit /b 1
    echo.
    python -m pip install --user "cryptography>=42.0.8,<47.0"
    if errorlevel 1 (
        echo.
        echo  A instalacao falhou. Tente a mao:
        echo      python -m pip install --user cryptography
        echo.
        pause
        exit /b 1
    )
    echo.
    echo  Pronto. Abrindo o painel.
)

rem ---------------------------------------------------------------------
rem 3. Abrir. pythonw evita o console preto atras da janela.
rem ---------------------------------------------------------------------
where pythonw >nul 2>&1
if errorlevel 1 (
    start "" python "admin.pyw"
) else (
    start "" pythonw "admin.pyw"
)
