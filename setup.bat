@echo off
chcp 65001 >nul
echo.
echo ================================================
echo  NotebookLM Connector - Setup do Cliente
echo ================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale em https://python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado

:: Instalar dependencias do cliente
echo.
echo [1/4] Instalando dependencias Python...
pip install -r client\requirements.txt -q
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas

:: Instalar Chromium para Playwright
echo.
echo [2/4] Instalando Chromium ^(Playwright^)...
python -m playwright install chromium
if errorlevel 1 (
    echo [ERRO] Falha ao instalar Chromium
    pause
    exit /b 1
)
echo [OK] Chromium instalado

:: Instalar notebooklm-py
echo.
echo [3/4] Instalando notebooklm-py...
pip install "notebooklm-py[browser]" -q
if errorlevel 1 (
    echo [ERRO] Falha ao instalar notebooklm-py
    pause
    exit /b 1
)
echo [OK] notebooklm-py instalado

:: Instalar skill no Claude Code
echo.
echo [4/4] Instalando skill no Claude Code...
notebooklm skill install --scope user --target claude
if errorlevel 1 (
    echo [AVISO] Falha ao instalar skill automaticamente
    echo         Instale manualmente clicando duas vezes em:
    echo         client\plugin\aaa-notebooklm.skill
) else (
    echo [OK] Skill notebooklm instalada no Claude Code
)

:: Instalar skill customizada
echo.
echo Instalando skill aaa-notebooklm...
set SKILL_DST=%USERPROFILE%\.claude\skills\aaa-notebooklm
if exist "%SKILL_DST%" rmdir /s /q "%SKILL_DST%"
xcopy /e /i /q client\plugin "%SKILL_DST%" >nul
echo [OK] Skill aaa-notebooklm instalada em %SKILL_DST%

echo.
echo ================================================
echo  Setup concluido!
echo ================================================
echo.
echo Proximos passos (a chave Fernet NUNCA fica nesta maquina):
echo   1. Defina a connector key: set NOTEBOOKLM_CONNECTOR_API_KEY=^<peca ao admin^>
echo   2. Conecte: python client\connect.py --email seu@email.com --nome "Nome"
echo      (faz login Google e sobe o token cifrado; seu acesso entra PENDENTE)
echo   3. Um admin ativa seu acesso e define seu nivel (POST /api/admin/users)
echo.
echo Para instalar o plugin no Claude Code:
echo   Clique duas vezes em: client\plugin\aaa-notebooklm.skill
echo.
pause
