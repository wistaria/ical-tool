# ical-tool

[English](README.md) | [日本語](README-ja.md)

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Author](https://img.shields.io/badge/author-Synge%20Todo-blue)](https://github.com/wistaria)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

iCalendar を操作するための便利なスクリプト集です。

## 使い方

```sh
./ical-tool --input=https://example.com/calendar.ics --output=output.ics
```

起動スクリプトは、仮想環境をプロジェクトの外に保存します。保存先は macOS では
`~/Library/Caches/ical-tool/venvs/`、Linux では `~/.cache/ical-tool/venvs/` です。
どちらの OS でも、`XDG_CACHE_HOME` に絶対パスを指定するとキャッシュの保存先を変更できます。
キャッシュはソースツリーの外に置く必要があります。

仮想環境は、プロジェクトの場所、Python インタープリタとそのバージョン、
`requirements.txt` の内容によって識別されます。これらに変更がなければ既存の環境を再利用し、
変更があれば新しい環境を作成して依存関係をインストールし直します。古い環境はキャッシュに残ります。
インストールに失敗した場合は次回の起動時に再試行します。同時に起動した場合は、初期化処理をロックで制御します。

`uv` が利用できる場合は、`uv` で Python インタープリタを選び、環境を作成して依存関係を
インストールします。それ以外の場合は `python3 -m venv` と `pip` を使います。
特定の Python バージョンを使うには、`ICAL_TOOL_PYTHON` にインタープリタのパスを指定します。

起動スクリプトとテスト実行スクリプトはバイトコードの書き込みを無効にするため、ソースツリーに
`__pycache__` や `.pyc` ファイルを作成しません。Python は隔離モードで実行し、
依存関係とインストーラのキャッシュはキャッシュディレクトリ内に保存します。インストール時は
pip と uv の設定ファイルを読み込まず、Python を自動でダウンロードすることもありません。
既存の Python 環境やシェル設定は変更しません。ICS ファイルは指定された出力先にのみ書き込みます。

`--input` には HTTP/HTTPS の URL またはローカルファイル名を指定できます。複数回指定すると、
複数の入力を 1 つのカレンダーに統合します。最初のカレンダーのプロパティを保持し、
すべての入力のコンポーネントを含めます。同一のタイムゾーン定義はまとめますが、同じ `TZID` に
異なる定義がある場合はエラーになります。

`--input` を省略すると標準入力から ICS データを読み込み、`--output` を省略すると標準出力に
ICS データを書き込みます。標準入力や標準出力を明示するために `-` を指定することもできます。
診断メッセージや環境構築時のメッセージは標準エラー出力に送ります。

```sh
./ical-tool --input=first.ics --input=second.ics --output=merged.ics
./ical-tool --remove-prop=LOCATION < input.ics > output.ics
./ical-tool --input=calendar.ics > output.ics
```

イベントのプロパティは、明示的に指定した場合にのみ削除または置換します。

`--days` を省略すると、すべてのエントリを保持します。指定した場合は、実行環境のタイムゾーンで
指定日数前の午前 0 時を基準とし、その時点以降に一度も発生しないイベントを削除します。
`--days=0` は今日以降に発生するイベントを保持します。負の値は指定できません。

削除するプロパティは `--remove-prop` で指定します。置換するプロパティ名と置換文字列は
`--replace-prop` で指定します。

```sh
./ical-tool --input=https://example.com/calendar.ics --output=output.ics \
  --days=30 \
  --remove-prop=LOCATION --remove-prop=DESCRIPTION \
  --replace-prop="SUMMARY=Busy" --replace-prop="ORGANIZER=mailto:busy@example.com"
```

`--remove-prop` は複数回指定でき、指定したプロパティだけを削除します。
`--replace-prop` も複数回指定でき、指定したプロパティだけを置換します。
これらのオプションを省略すると、`SUMMARY` を含むイベントのプロパティをそのまま保持します。
プロパティ名は大文字と小文字を区別しません。

置換は削除の後に適用し、存在しないプロパティは追加します。同じプロパティを複数回指定した場合は、
最後に指定した値を使います。値は空文字列にでき、`=` を含めることもできます。
`--summary="Busy"` は `--replace-prop="SUMMARY=Busy"` の短縮指定として引き続き利用でき、
適用順序も同じルールに従います。テキスト以外のプロパティには iCalendar 形式の値を指定します。
たとえば `--replace-prop="DTSTART=20261231T120000Z"` や
`--replace-prop="GEO=35.0;139.0"` です。アラームは常に削除します。

## テスト

テスト実行スクリプトは `ical-tool` と同じキャッシュ領域の仮想環境を使い、必要に応じて
`requirements.txt` に記載された依存関係を自動でインストールします。

```sh
./run-tests
./run-tests -p test_cli.py
```

GitHub Actions は push と pull request 時に Python 3.11 と 3.14 で `./run-tests` を実行し、
各インタープリタに対応するキャッシュ領域の仮想環境を使います。Actions タブから手動で
ワークフローを開始することもできます。
