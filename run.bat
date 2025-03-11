@echo off
setlocal

REM 仮想環境のディレクトリ名
set VENV_DIR=venv

REM 仮想環境がなければ作成
if not exist %VENV_DIR% (
    python -m venv %VENV_DIR%
)

REM 仮想環境を有効化
call %VENV_DIR%\Scripts\activate

REM 必要なライブラリのリスト
set LIBS=pillow pandas matplotlib cartopy scipy

REM ライブラリの欠如をチェック
set "MISSING=0"
for %%L in (%LIBS%) do (
    python -c "import %%L" 2>nul || (
        set "MISSING=1"
        goto :break_loop
    )
)
:break_loop

REM 欠如があれば pip をアップグレード
if "%MISSING%"=="1" (
    python -m pip install --upgrade pip
)

REM 足りないライブラリのみインストール
for %%L in (%LIBS%) do (
    python -c "import %%L" 2>nul || pip install %%L
)

REM Pythonスクリプトを実行
python LocaIndex_Manager.py

endlocal
REM pause
