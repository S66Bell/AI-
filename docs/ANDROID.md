# JARVIS を Android スマホだけで動かす(完全無料・オフライン)

このガイドでは、Android スマホの中で小さな言語モデルを動かし、スマホのブラウザから
JARVIS を使う手順を説明します。クラウドも API キーも不要で、一度モデルを
ダウンロードすればオフラインで動きます。

## 必要なもの

- Android 7 以上のスマホ(RAM 6GB 以上推奨。4GB でも 1.5B モデルなら動きます)
- 空き容量 3GB 程度
- [Termux](https://f-droid.org/packages/com.termux/)(F-Droid 版。Play ストア版は古いので不可)
- 任意: [Termux:API](https://f-droid.org/packages/com.termux.api/)(画面オフ中もスリープしないようにする)

## セットアップ(初回のみ)

Termux を開いて次を実行します。

```bash
pkg install -y git
git clone https://github.com/s66bell/AI-.git jarvis
cd jarvis
bash scripts/termux/setup.sh
```

スクリプトがやること:

1. Python と llama.cpp(`llama-server`)をインストール
2. JARVIS の依存ライブラリをインストール(すべて純 Python なのでビルド不要)
3. Hugging Face から Qwen2.5-3B-Instruct(約 2GB)をダウンロード
4. `.env` を作成し、JARVIS をスマホ内のモデルサーバーに向ける

モデルサイズはスマホの RAM に合わせて選べます。

| RAM | 設定 | 速度の目安 |
| --- | --- | --- |
| 4GB | `JARVIS_MODEL_SIZE=1.5b bash scripts/termux/setup.sh` | 速い。簡単な会話・検索向き |
| 6〜8GB | `bash scripts/termux/setup.sh`(既定の 3b) | バランス型。エージェント用途の下限 |
| 12GB 以上 | `JARVIS_MODEL_SIZE=7b bash scripts/termux/setup.sh` | 賢いが遅い(1 秒に数トークン) |

## 起動

```bash
cd ~/jarvis
bash scripts/termux/start.sh
```

`llama-server` が起動してから JARVIS の Web UI が立ち上がります。スマホの
Chrome で <http://localhost:8765> を開いてください。メニューの
「ホーム画面に追加」を選ぶと、普通のアプリのように起動できます。

停止は Ctrl-C、または別のセッションで `bash scripts/termux/stop.sh` です。

## 使い方

画面は 4 つのタブに分かれています。

- **チャット** 普通の会話。JARVIS は必要に応じてツール(Web 検索、ページ取得、
  シェル、ファイル、記憶)を自分で使います。危険なコマンドは実行前に確認画面が
  出ます。マイクボタンで音声入力、「記憶」タブの設定で読み上げもできます。
- **タスク** 目標を渡すと、JARVIS がバックグラウンドで計画→実行→自己チェック
  →報告まで一人でやります。進捗はリアルタイムで見られ、途中で中止もできます。
  チャットから「〜を調べておいて」と頼んでも、JARVIS が自分でタスクを作ります。
- **定期実行** 「毎日 8:00 に〜」「60 分ごとに〜」という形で、タスクを自動で
  繰り返します。スマホがスリープしていた分は、起動後に 1 回だけまとめて実行
  されます。
- **記憶** JARVIS が覚えている事実の一覧。追加・削除ができます。

## 他の端末から使う

同じ Wi-Fi の PC やタブレットからも使えます。`.env` を次のように変え、
必ずトークンを設定してください。

```
JARVIS_WEB_HOST=0.0.0.0
JARVIS_WEB_TOKEN=好きな長い文字列
```

ブラウザで `http://<スマホのIP>:8765` を開くとトークンを聞かれます。外出先からも
使いたい場合は [Tailscale](https://tailscale.com/)(個人利用は無料)を入れると、
ポートを公開せずに安全につながります。

## 調整のヒント

- **遅い / メモリ不足で落ちる**: `JARVIS_CTX=4096 bash scripts/termux/start.sh`
  でコンテキストを縮める。それでも駄目なら 1.5B モデルに。
- **ツールを使ってくれない**: モデルが小さいほどツール呼び出しが不安定です。
  3B 以上を推奨。JARVIS はモデルがツール呼び出しをテキストで書いてしまった場合も
  解釈します。
- **バッテリー**: 画面オフ中も動かすには Termux:API を入れ、Android の
  電池最適化から Termux を除外してください。
- **モデルを変える**: `~/models` に別の GGUF を置き、
  `JARVIS_MODEL_PATH=~/models/xxx.gguf bash scripts/termux/start.sh`。
  ツール呼び出しに対応したモデル(Qwen2.5 / Qwen3 / Llama 3.x 系)を選んでください。
- **PC で動かしているモデルにつなぐ**: `.env` の `JARVIS_OPENAI_BASE_URL` を
  PC の llama-server / LM Studio / Ollama(`http://<PC>:11434/v1`)に向けるだけで、
  スマホ側はそのまま使えます。
