@echo off
rem Duplo clique aqui. Abre a janela de conexao.
rem
rem pythonw em vez de python: nao deixa janela preta de console atras da
rem interface. Se o pythonw nao estiver no PATH, cai para o python normal.

cd /d "%~dp0"

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw "app.pyw"
    exit /b
)

where python >nul 2>&1
if %errorlevel%==0 (
    start "" python "app.pyw"
    exit /b
)

echo.
echo  Python nao encontrado neste computador.
echo.
echo  Instale em https://python.org/downloads
echo  Marque "Add Python to PATH" durante a instalacao.
echo.
pause
