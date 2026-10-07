# SayItRight

英語には「綴りと発音のギャップが大きい単語」(黙字、`-ough`のような特殊な綴りパターンなど)がたくさんあります。このリポジトリは、そうした「発音が難しい英単語」を毎日1語自動で選び、発音動画を生成してYouTubeに投稿するパイプラインです。

## パイプライン全体の流れ

`.github/workflows/fetch_candidates.yml` が以下のスクリプトを順番に実行します(手動実行、または外部の cron-job.org から `workflow_dispatch` を毎日呼び出す運用)。

```
fetch_and_score.py  … cmudict(13万語超)から「発音が難しい単語」を1語選び candidates.json に出力
        ↓
generate_audio.py   … candidates.json の単語をGoogle Cloud TTSで音声化(通常速度/スロー) → audio_output/
        ↓
create_videos.py    … 音声+IPA発音記号からPlaywright/moviepyで動画・サムネイルを生成
                       → video_output/(Shorts, 9:16), regular_video_output/(通常動画, 16:9), thumbnail_output/
        ↓
upload_videos.py    … Shorts・通常動画・サムネイルをYouTubeにアップロードし、
                       日本語ローカライズ・意味/例文入り説明欄を設定
                       さらに概要欄と同内容(ハッシュタグ除く)をコメントにも投稿
```

- 単語の選定は `used_words.json`(使用済み単語の履歴)を見て重複を避け、さらに直近の投稿と綴りパターン(黙字系・`-ough`系など)が被らないよう多様性も考慮します。
- `used_words.json` への登録は **YouTubeへのアップロードが成功した時点で初めて** 行われます。TTS/動画生成/アップロードのいずれかで失敗した単語は「使用済み」にならず、次回また候補に上がります。
- 1単語につき、Shorts(縦型9:16)と通常動画(横型16:9、単語をキャンバスいっぱいに大きく表示するレイアウト)を同時に2本アップロードします。通常動画の生成・アップロードが失敗してもShortsの投稿は継続します(通常動画だけがスキップされます)。

## ディレクトリ構成

| ファイル | 役割 |
| --- | --- |
| `config.py` | パイプライン全体で共有する運用パラメータ(ファイルパス・プールサイズ・リトライ回数・TTSボイス設定など)を一元管理 |
| `score_words.py` | 「綴りと発音のギャップ」に基づく単語の難易度スコアリングロジック |
| `fetch_and_score.py` | cmudict + 頻出単語リストから候補単語を選び `candidates.json` を出力 |
| `arpabet_to_ipa.py` | ARPAbet(CMU辞書の発音表記) → IPA(国際音声記号)変換 |
| `generate_audio.py` | Google Cloud Text-to-Speechで音声(通常/スロー)を生成 |
| `video_builder.py` | Playwrightでのスクリーンショット撮影とmoviepyでの動画合成(Shorts用9:16縦型・通常動画用16:9横型・サムネイル) |
| `create_videos.py` | `video_builder.py` を使って候補単語ごとに動画・サムネイルを生成 |
| `upload_videos.py` | YouTubeへのShorts/通常動画/サムネイルのアップロード、説明欄への意味・例文追加、日本語ローカライズ設定、再生リストへの追加 |
| `used_words.json` | 使用済み単語の履歴(`{"word": ..., "patterns": [...]}` の配列、古い→新しい順) |
| `candidates.json` | 直近の `fetch_and_score.py` 実行で選ばれた候補単語 |
| `tests/` | `score_words.py` / `arpabet_to_ipa.py` (外部依存のない純粋関数)のユニットテスト |
| `.github/workflows/fetch_candidates.yml` | 本番パイプライン一式を実行するワークフロー |
| `.github/workflows/tests.yml` | lint(ruff) + pytest を実行するCIワークフロー |

## 必要な環境変数 / GitHub Secrets

本番ワークフロー(`fetch_candidates.yml`)の実行には以下が必要です。

| 変数名 | 用途 |
| --- | --- |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | GCPサービスアカウントキー(JSON文字列)。Text-to-Speech APIの呼び出しに使用 |
| `YT_REFRESH_TOKEN` / `YT_CLIENT_ID` / `YT_CLIENT_SECRET` | YouTube Data API用のOAuth認証情報 |
| `YT_PRIVACY_STATUS`(任意) | アップロードする動画の公開設定。省略時は `public`。初回運用時は `unlisted` を推奨 |
| `YOUTUBE_SHORTS_PLAYLIST_ID`(任意) | Shorts用再生リストのID。設定するとアップロード成功時に自動追加される。未設定の場合は追加をスキップ |
| `YOUTUBE_COMPILATION_PLAYLIST_ID`(任意) | 通常動画用再生リストのID。同上(Secret名は旧・結合動画機能の名残だが、現在は単語単位の通常動画用に使っている) |

**OAuthスコープについて**: 動画アップロード(`videos.insert`)・サムネイル設定(`thumbnails.set`)には `youtube.upload` スコープで足りますが、日本語ローカライズ設定(`videos.update`)・再生リストへの追加(`playlistItems.insert`)には `youtube`(または `youtube.force-ssl`)スコープが必要です。コメント投稿(`commentThreads.insert`)は `youtube.force-ssl` スコープのみ対応で、`youtube` スコープだけでは403エラーで失敗します(他の2つとは必要スコープが異なる点に注意)。不足しているスコープがあっても動画本体のアップロードには影響しません(該当処理のみ警告ログを出して継続します)。

## ローカルでの実行

```bash
pip install -r requirements.txt
python fetch_and_score.py      # candidates.json を生成
python generate_audio.py       # 要 GOOGLE_APPLICATION_CREDENTIALS
python create_videos.py        # 要 playwright install --with-deps chromium, ffmpeg
python upload_videos.py        # 要 YT_REFRESH_TOKEN 等
```

## テスト・Lint

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

`score_words.py` / `arpabet_to_ipa.py` は外部依存のない純粋関数なので、`requirements-dev.txt` は `pytest`/`ruff` のみの軽量構成にしています。

## 運用上の注意

- **同時実行**: `fetch_candidates.yml` は `concurrency` で同時実行を1本に制限しています。手動実行と定期実行が重なった場合、後続はキャンセルされずキューで待機します。
- **API使用量**: `generate_audio.py` / `upload_videos.py` は実行完了時に、TTS呼び出し回数・YouTube Data APIの概算クォータ消費量をログに出力します。GCP Consoleのクォータ画面を都度開かなくても、実行ログだけで使用量の目安を確認できます。
