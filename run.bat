@echo off
setlocal

REM 仮想環境のディレクトリ名
set VENV_DIR=venv

REM 既存の環境がなければ作成
if not exist %VENV_DIR% (
    python -m venv %VENV_DIR%
    call %VENV_DIR%\Scripts\activate
    python -m pip install --upgrade pip
    pip install pillow
) else (
    call %VENV_DIR%\Scripts\activate
)

REM Pythonスクリプトを実行
python LocaIndex_Manager.py

endlocal
REM pause
