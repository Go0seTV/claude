@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem --- Trouve Python (lanceur "py" ou "python") ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python est introuvable. Installe-le depuis https://www.python.org
    echo en cochant bien "Add python.exe to PATH".
    pause
    exit /b 1
)

rem --- Installe mutagen la premiere fois ---
%PY% -c "import mutagen" >nul 2>&1
if errorlevel 1 (
    echo Installation des composants necessaires, une seule fois...
    %PY% -m pip install --user -r requirements.txt
    if errorlevel 1 (
        echo L'installation a echoue. Verifie ta connexion internet.
        pause
        exit /b 1
    )
)

rem --- Lance l'application sans fenetre noire ---
if "%PY%"=="py -3" (
    start "" pyw -3 app.pyw
) else (
    start "" pythonw app.pyw
)
