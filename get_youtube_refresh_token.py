#!/usr/bin/env python3
"""
YouTube Data API 用リフレッシュトークンを、開発者のローカルマシンで一度だけ
取得するためのヘルパースクリプト。

GitHub Actions側(youtube_upload.py)はブラウザ操作ができないCI環境なので、
対話的なOAuth同意フローをそこで実行することはできない。そのため、このスク
リプトを手元で一度だけ実行してリフレッシュトークンを取得し、それを
GitHub Secretsに登録しておく運用にしている(取得したトークンは以後失効
しない限り使い回せる)。

事前準備(Google Cloud Console):
    1. プロジェクトを作成し、「YouTube Data API v3」を有効化する
    2. 「OAuth同意画面」を設定する(公開ステータスは「テスト」のままでよい。
       その場合は自分のGoogleアカウントを「テストユーザー」に追加すること)。
       「データアクセス」→「スコープを追加または削除」で、下記SCOPESに
       書いてあるものと同じスコープを追加しておくこと(登録していないスコー
       プはリクエストしても正しく付与されないことがある)
    3. 「認証情報」→「OAuthクライアントIDを作成」で、種類は
       「デスクトップアプリ」を選んで作成する
       (このスクリプトはループバックアドレス http://localhost でリダイレクト
        を受け取るため、デスクトップアプリ種別である必要がある)

重要: 1つのGoogleアカウントに複数のYouTubeチャンネル(ブランドアカウント)
が紐づいている場合、Googleは認可の途中で「どのチャンネルとして許可します
か」という選択画面を出す。このスクリプトは prompt に select_account を
含めることでその選択画面を強制的に表示させている(省略すると選択画面が
スキップされ、そのアカウントの「デフォルト」チャンネルが黙って選ばれてし
まい、意図しないチャンネルに紐づいたトークンが発行されることがある)。
ブラウザで選択画面が出たら、必ず意図したチャンネルをクリックすること。

使い方:
    pip install -r requirements-dev.txt
    python3 get_youtube_refresh_token.py --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET

実行するとブラウザが開いてGoogleアカウントでの認可、続いてチャンネルの
選択を求められる。認可するとリフレッシュトークンが標準出力に表示される
ので、それを YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET /
YOUTUBE_REFRESH_TOKEN として GitHub Secretsに登録する。表示されるチャン
ネル名が意図したものか、必ず確認すること。

同時に表示される今日の日付も YOUTUBE_REFRESH_TOKEN_ISSUED_AT として登録
しておくと、OAuth同意画面が「テスト」ステータスの場合の既知の7日失効
ルールが近づいた/過ぎた際に、generate.py / compile_shorts.py の実行ログに
警告が出るようになる(任意だが強く推奨)。
"""

import argparse
import datetime

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# youtube (フルアクセス) 1つで、アップロードとチャンネル確認(channels.list)
# の両方をカバーする。youtube.upload だけを個別に要求すると、OAuth同意画面
# 側にそのスコープが登録されていない場合に正しく付与されないことがあるため、
# 同意画面の「機密性の高いスコープ」に登録した youtube / youtube.readonly と
# 一致させている。
SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def main():
    ap = argparse.ArgumentParser(description="YouTubeアップロード用リフレッシュトークンの取得")
    ap.add_argument("--client-id", required=True, help="OAuthクライアントID")
    ap.add_argument("--client-secret", required=True, help="OAuthクライアントシークレット")
    args = ap.parse_args()

    client_config = {
        "installed": {
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # select_account: 複数チャンネルを持つアカウントでチャンネル選択画面を
    #   強制的に表示させる(無いとデフォルトチャンネルが黙って選ばれる)
    # consent: 2回目以降の認可でもrefresh_tokenが確実に返るようにする
    #   (省略すると初回以外はNoneになることがある)
    credentials = flow.run_local_server(port=0, prompt="consent select_account")

    issued_at = datetime.date.today().isoformat()

    print("\n取得できました。以下をGitHub Secretsに登録してください:\n")
    print(f"  YOUTUBE_CLIENT_ID={args.client_id}")
    print(f"  YOUTUBE_CLIENT_SECRET={args.client_secret}")
    print(f"  YOUTUBE_REFRESH_TOKEN={credentials.refresh_token}")
    print(f"  YOUTUBE_REFRESH_TOKEN_ISSUED_AT={issued_at}"
          "  (任意だが強く推奨。7日失効が近づいた際の警告に使われる)")

    try:
        youtube = build("youtube", "v3", credentials=credentials)
        channels = youtube.channels().list(part="id,snippet", mine=True).execute().get("items", [])
        if channels:
            ch = channels[0]
            print(f"\n認可されたチャンネル: {ch['snippet']['title']} (id={ch['id']})")
            print("  -> このチャンネルが意図したものであることを確認してください。")
            print(f"  -> 誤アップロード防止のため、任意で YOUTUBE_CHANNEL_ID={ch['id']} も"
                  " GitHub Secretsに登録することを推奨します。")
        else:
            print("\n警告: このアカウントに紐づくYouTubeチャンネルが見つかりませんでした。")
    except Exception as e:  # noqa: BLE001 - 確認用の付加情報なので失敗しても致命的ではない
        print(f"\n(チャンネル確認に失敗しましたが、トークン自体は取得済みです: {e})")


if __name__ == "__main__":
    main()
