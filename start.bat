@echo off
REM 青色申告 複式簿記 - ローカル版 起動スクリプト (Windows用)
cd /d "%~dp0"

pause

REM 仮想環境がなければ作成
if not exist venv (
  echo 初回起動: Python仮想環境を作成しています...
  python -m venv venv
  venv\Scripts\pip install --upgrade pip
  venv\Scripts\pip install -r requirements.txt
)

REM アプリ起動
echo アプリを起動します...
venv\Scripts\python app.py
pause
