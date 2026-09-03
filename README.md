# SayItRight

英語には「綴りと発音のギャップが大きい単語」(黙字、`-ough`のような特殊な綴りパターンなど)がたくさんあります。このリポジトリは、そうした「発音が難しい英単語」を毎日1語自動で選び、発音動画を生成してYouTubeに投稿するパイプラインです。

## パイプライン全体の流れ

`.github/workflows/fetch_candidates.yml` が以下のスクリプトを順番に実行します(手動実行、または外部の cron-job.org から `workflow_dispatch` を毎日呼び出す運用)。

```
fetch_and_score.py  … cmudict(13万語超)から「発音が難しい単語」を1語選び candidates.json に出力
        ↓
generate_audio.py   … candidates.json の単語をGoogle Cloud TTSで音声化(通常速度/スロー) → audio_output/
        ↓
create_videos.py    … 音声+IPA発音記号からPlaywright/moviepyで動画を生成 → video_output/
        ↓
upload_videos.py    … 動画をYouTubeにアップロードし、日本語ローカライズ・意味/例文入り説明欄を設定
```

- 単語の選定は `used_words.json`(使用済み単語の履歴)を見て重複を避け、さらに直近の投稿と綴りパターン(黙字系・`-ough`系など)が被らないよう多様性も考慮します。
- `used_words.json` への登録は **YouTubeへのアップロードが成功した時点で初めて** 行われます。TTS/動画生成/アップロードのいずれかで失敗した単語は「使用済み」にならず、次回また候補に上がります。

## ディレクトリ構成

| ファイル | 役割 |
| --- | --- |
| `config.py` | パイプライン全体で共有する運用パラメータ(ファイルパス・プールサイズ・リトライ回数・TTSボイス設定など)を一元管理 |
| `score_words.py` | 「綴りと発音のギャップ」に基づく単語の難易度スコアリングロジック |
| `fetch_and_score.py` | cmudict + 頻出単語リストから候補単語を選び `candidates.json` を出力 |
| `arpabet_to_ipa.py` | ARPAbet(CMU辞書の発音表記) → IPA(国際音声記号)変換 |
| `generate_audio.py` | Google Cloud Text-to-Speechで音声(通常/スロー)を生成 |
| `video_builder.py` | Playwrightでのスクリーンショット撮影とmoviepyでの動画合成(9:16縦型Shorts) |
| `create_videos.py` | `video_builder.py` を使って候補単語ごとに動画を生成 |
| `upload_videos.py` | YouTubeへの動画アップロード、説明欄への意味・例文追加、日本語ローカライズ設定 |
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

**OAuthスコープについて**: 動画アップロード(`videos.insert`)には `youtube.upload` スコープで足りますが、日本語ローカライズ設定(`videos.update`)には `youtube`(または `youtube.force-ssl`)スコープが必要です。`youtube.upload` のみで発行した `YT_REFRESH_TOKEN` だと、ローカライズ設定だけが403エラーで失敗します(動画本体のアップロードには影響しません)。

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
