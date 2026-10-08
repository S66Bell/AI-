# MIRA を Mac で動かし、スマホから使う

Mac(Apple Silicon 推奨、RAM 16GB 以上)でモデルと MIRA を動かし、スマホは
ブラウザでつなぐ構成です。Metal(GPU)で動くので、スマホ内で動かすより
桁違いに速く、14B クラスの賢いモデルが使えます。会話内容は Mac から外に出ません。

## 必要なもの

- macOS(Apple Silicon なら M1 以降どれでも。RAM 24GB なら 14B モデルが快適)
- [Homebrew](https://brew.sh)(未導入なら、サイトの 1 行コマンドで入れる)
- 空き容量 15GB 程度(14B モデルは約 9GB)

## セットアップ(初回のみ)

ターミナルで:

```bash
git clone https://github.com/S66Bell/AI-.git mira
cd mira
bash scripts/mac/setup.sh
```

スクリプトがやること:

1. Homebrew で llama.cpp(Metal 対応)と Python 3.12 をインストール
2. 仮想環境を作って MIRA の依存ライブラリを入れる
3. RAM に合わせてモデルを自動選択してダウンロード
4. `.env` を作成(スマホからつなぐためのアクセストークンも自動生成)

| RAM | 自動選択 | サイズ | 目安 |
| --- | --- | --- | --- |
| 12〜19GB | 7B | 約 4.7GB | 速い |
| 20〜39GB | 14B | 約 9GB | 賢さと速さのバランス(24GB Mac の既定) |
| 40GB 以上 | 32B | 約 20GB | かなり賢い |

別のサイズにしたいときは `JARVIS_MODEL_SIZE=7b bash scripts/mac/setup.sh`。

## 起動

```bash
bash scripts/mac/start.sh
```

起動すると、Mac 用とスマホ用の URL、アクセストークンが表示されます。

```
    this Mac:   http://localhost:8765/
    phone:      http://192.168.x.x:8765/   token: xxxxxxxx
```

スマホ(同じ Wi-Fi)の Chrome で `phone:` の URL を開き、聞かれたらトークンを
入力します(1 回入れれば記憶されます)。Mac のターミナルを閉じると止まります。
Ctrl-C で停止、または `bash scripts/mac/stop.sh`。

## ログイン時に自動起動(常駐)

```bash
bash scripts/mac/install-service.sh
```

以後、Mac にログインしている間は MIRA が常に動き、落ちても自動で再起動します。
ログは `tail -f ~/.jarvis/mac.log`。やめるときは
`bash scripts/mac/install-service.sh remove`。

スリープ中はスマホからつながりません。`start.sh` は電源接続中のスリープを
防ぎます(`caffeinate`)。ノートの場合は電源につないでフタを開けたままにするか、
システム設定 → バッテリー → 電源アダプタ接続時に「ディスプレイがオフのときに
自動でスリープさせない」をオンにしてください。

## 外出先から使う(Tailscale)

[Tailscale](https://tailscale.com/)(個人利用は無料)で、ポート開放なしに、
あなたのアカウントでログインした端末だけが MIRA に届くようにします。通信は
端末間で暗号化され、HTTPS になるのでスマホの**マイク入力とホーム画面アプリ化**も
使えます。LAN からの直接接続は閉じるので、これが最も安全な使い方です。

1. スマホに Tailscale アプリ(Play ストア / App Store)を入れて、Google や GitHub
   などでログイン(アカウントは Mac と同じものを使う)
2. Mac で次を実行(Tailscale のインストール → ログイン案内 → HTTPS 配信 → LAN を閉じる)

```bash
bash scripts/mac/tailscale.sh
```

   初回はログインを求められるので、メニューバーの Tailscale からログインして、
   もう一度同じコマンドを実行します。
3. 表示された `https://<Macの名前>.<tailnet>.ts.net/` をスマホで開き、トークンを入力。
   Chrome のメニューから「ホーム画面に追加」すると、アプリのように使えます。
4. `bash scripts/mac/start.sh` で再起動(常駐サービスにしていれば自動)

やめるときは `bash scripts/mac/tailscale.sh off`(LAN からの接続を再び許可)。

「HTTPS Certificates」のエラーが出たら、<https://login.tailscale.com/admin/dns> で
MagicDNS と HTTPS Certificates を有効にして、スクリプトをもう一度実行してください。

## Windows や他の PC から使う

Mac がサーバーのままで、Windows・iPad・別の Mac からも使えます。入れるのは
Tailscale だけで、MIRA 側の設定変更は不要です。

1. Windows に [Tailscale](https://tailscale.com/download/windows) をインストールし、
   Mac と**同じアカウント**でログイン(タスクトレイのアイコンが接続状態になる)
2. Edge か Chrome で `https://<Macの名前>.<tailnet>.ts.net/` を開き、トークンを入力
   (Mac の `.env` の `JARVIS_WEB_TOKEN`。`grep JARVIS_WEB_TOKEN ~/mira/.env` で確認)
3. アプリのように使いたいときは、Edge なら「アプリ」→「このサイトをアプリとして
   インストール」、Chrome ならアドレスバー右端のインストールアイコン

PC では Enter で送信、Shift+Enter で改行です。会話履歴・記憶・タスクはすべて
Mac 側にあるので、スマホと PC で同じ MIRA を続きから使えます。同じ Wi-Fi に
いる必要はありません(Tailscale 経由)。

## 自己学習

MIRA は使うほど「あなた向け」になります(モデルの重みは変えず、記憶で学びます)。

- **接し方**: 返事の下の 👎 や「もっと短く」などの訂正から、振る舞いのルールを自分で作ります。記憶タブで確認・削除できます。
- **知識**: 「このページを覚えて https://…」「この文章を覚えて …」と頼むか、記憶タブの入力欄に貼ると、関連する質問のときに自動で参照します。
- **やり方**: バックグラウンドタスクの完了ごとに教訓を書き残し、似た作業のときに参照します。

## セキュリティ

既定で、トークン認証、プライベートネットワーク限定、ファイル操作のサンドボックス、
全シェルコマンドの確認制が有効です。詳細と調整は [SECURITY.md](SECURITY.md)。

## 頭脳を切り替える

- Groq の無料枠(超高速、会話は Groq のサーバーへ): `bash scripts/brain.sh groq gsk_キー`
- Mac のローカルモデルに戻す: `bash scripts/brain.sh local`

切り替えたら `start.sh` を実行し直してください。

## うまくいかないとき

- **`llama-server exited`**: `tail -n 30 ~/.jarvis/llama-server.log` を確認。メモリ不足なら
  `JARVIS_MODEL_SIZE=7b bash scripts/mac/setup.sh` で小さいモデルに。
- **スマホからつながらない**: 同じ Wi-Fi か、Mac のファイアウォールで Python の
  受信を許可しているか(システム設定 → ネットワーク → ファイアウォール)を確認。
- **返事が遅い**: `grep -E "prompt eval time|eval time" ~/.jarvis/llama-server.log | tail -n 4`
  で速度を確認。14B なら読み込み数百トークン/秒、生成 15〜25 トークン/秒が目安。
- **ポート 8080 が他のアプリと衝突**: `JARVIS_LLM_PORT=8081 bash scripts/mac/start.sh` にし、
  `.env` の `JARVIS_OPENAI_BASE_URL` も `http://127.0.0.1:8081/v1` に変更。
