# MIRA を Android スマホだけで動かす(完全無料・オフライン)

(プロジェクト名や設定項目は `JARVIS_*` のままですが、アシスタント本人は
「MIRA」。親友みたいにフランクに日本語で話します。名前は `.env` の
`JARVIS_NAME`、あなたの呼び名は `JARVIS_USER_NAME` で変えられます)

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

モデルサイズはスマホの RAM から自動で選ばれます(`JARVIS_MODEL_SIZE=` で上書き可)。

| RAM | 自動選択 | サイズ | 特徴 |
| --- | --- | --- | --- |
| 〜5GB | 1.5b | 約 1.1GB | 速い。簡単な会話・検索向き |
| 6〜8GB | 3b | 約 2.0GB | バランス型。エージェント用途の下限 |
| 10GB 以上 | 7b | 約 4.7GB | 賢い。ツール呼び出しが安定し、エージェント向き |

### Galaxy S26 の場合

RAM 12GB なので **7B が自動で選ばれます**。7B を 4bit 量子化したモデルは
約 5GB をメモリに載せるため、他のアプリを閉じた状態で使ってください。
生成速度は 1 秒あたり数トークン程度で、ひとつの返事に 10〜30 秒かかる
ことがあります。`start.sh` はスマホの高性能コアだけを使う設定(6 スレッド)
で起動します。

もっと速さが欲しいときは `JARVIS_MODEL_SIZE=3b bash scripts/termux/setup.sh`
で 3B も入れておき、`JARVIS_MODEL_PATH=~/models/qwen2.5-3b-instruct-q4_k_m.gguf bash scripts/termux/start.sh`
のように切り替えられます。発熱が続くと Android が性能を落とすので、
長いバックグラウンドタスクを回すときはケースを外す・充電しながらにする
のがおすすめです。

## 起動

```bash
cd ~/jarvis
bash scripts/termux/start.sh
```

`llama-server` が起動してから JARVIS の Web UI が立ち上がります。スマホの
Chrome で <http://localhost:8765> を開いてください。メニューの
「ホーム画面に追加」を選ぶと、普通のアプリのように起動できます。

停止は Ctrl-C、または別のセッションで `bash scripts/termux/stop.sh` です。

「このサイトにアクセスできません」と出るときは、JARVIS がまだ起動していません。
`bash scripts/termux/doctor.sh` を実行して出力をそのまま貼ってください。
URL は `http://127.0.0.1:8765` でも試してみてください。

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

## 返事が遅いとき

返事の時間は「プロンプトの読み込み」と「文章の生成」の 2 つに分かれます。
スマホで効くのはほぼ前者で、前回の内容をキャッシュできているかで数十秒から
数分まで変わります。確認は次のコマンドで、`prompt eval time` の行を見ます。

```bash
grep -E "prompt eval time|eval time" ~/.jarvis/llama-server.log | tail -n 6
```

- `prompt eval time` の tokens が毎回数千 → キャッシュが効いていません。`git pull`
  して最新の `start.sh` で起動し直してください(`--cache-reuse` が有効になります)。
- 毎回数百 tokens なのに遅い → CPU が遅い/熱で性能が落ちています。
  `JARVIS_THREADS=4` や `=8` を試す、ケースを外す、3B モデルに切り替える。
- `eval time` の tokens per second が 3 未満 → モデルが大きすぎます。3B に。

### まず純粋な速度を測る

```bash
bash scripts/termux/bench.sh
```

MIRA を介さずにモデルの素の速度(読み込み pp / 生成 tg、トークン/秒)を、
パッケージ版と最適化ビルドの両方、スレッド数 2/4/6/8 で測ります。
**バッテリー 50% 以上、省電力モードをオフ、本体が冷えた状態**で測ってください。
低バッテリー時や発熱時は Android が CPU を強く制限し、10 倍以上遅くなります。
結果の一番速いスレッド数を `JARVIS_THREADS=4` のように `start.sh` に渡せます。

### 読み込みが 1 秒あたり 30 トークン以下のとき

Termux のパッケージ版 llama.cpp は汎用ビルドで、最近のスマホにある高速命令
(DOTPROD / I8MM)を使わないことがあります。`doctor.sh` の `--- cpu` に
`asimddp` や `i8mm` があるのに、`llama.cpp build` 側が `DOTPROD = 0` なら、
端末向けにビルドし直すと数倍速くなります(10〜20 分、充電しながら)。

```bash
bash scripts/termux/build-llama.sh
```

以後 `start.sh` は自動でこのビルドを使います。

3B への切り替えは次の 2 行です(7B は残るので戻せます)。

```bash
JARVIS_MODEL_SIZE=3b bash scripts/termux/setup.sh
JARVIS_MODEL_PATH=~/models/qwen2.5-3b-instruct-q4_k_m.gguf bash scripts/termux/start.sh
```

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
