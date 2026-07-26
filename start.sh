#!/bin/bash
# 青色申告 複式簿記 - ローカル版 起動スクリプト (Mac/Linux用)
cd "$(dirname "$0")"

# 仮想環境がなければ作成
if [ ! -d "venv" ]; then
  echo "初回起動: Python仮想環境を作成しています..."
  python3 -m venv venv
  ./venv/bin/pip install --upgrade pip
  ./venv/bin/pip install -r requirements.txt
fi

# アプリ起動
echo "アプリを起動します..."
./venv/bin/python app.py
