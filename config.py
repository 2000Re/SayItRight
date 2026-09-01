"""
パイプライン全体で共有する運用パラメータ(件数・しきい値・リトライ回数・
ファイルパスなど)を一元管理する。

配色やCTA文言などのコンテンツ寄りの値は、調整する際に該当スクリプトを
直接見た方がわかりやすいため、これまで通り各スクリプト内に残している。
"""

# --- 共有ファイルパス ---
CANDIDATES_PATH = "candidates.json"
USED_WORDS_PATH = "used_words.json"
AUDIO_DIR = "audio_output"
VIDEO_DIR = "video_output"
THUMBNAIL_DIR = "thumbnail_output"

# --- fetch_and_score.py: 単語選定 ---
COMMON_WORDS_URL = (
    "https://raw.githubusercontent.com/first20hours/google-10000-english/"
    "master/google-10000-english-usa-no-swears-medium.txt"
)
POOL_SIZE = 15       # スコア上位からこの件数をプール
PICK_N = 3           # 今回の動画用に実際に選ぶ件数(1回の実行で3本アップロード)
MIN_LETTERS = 4      # これより短い単語は除外
# 直近何件の投稿と綴りパターンの重複を避けるか。PICK_N=3で1回の実行あたり
# 3件消費するため、以前(PICK_N=1)と同じ日数分をカバーするよう3倍にしている。
RECENT_PATTERN_WINDOW = 15

# --- generate_audio.py: TTS ---
VOICE_NAME = "en-US-Neural2-D"  # 明瞭で聞き取りやすい男性ボイス(好みで変更可)
LANGUAGE_CODE = "en-US"
SPEAKING_RATES = {
    "normal": 1.0,
    "slow": 0.6,
}
MIN_EXPECTED_AUDIO_SECONDS = 1.2  # break(300+800+500ms=1.6s)より短ければ明らかに異常
TTS_MAX_RETRIES = 3
TTS_RETRY_BACKOFF_SECONDS = 2
AUDIO_PAD_MS = 3000  # 前後に付与する無音の長さ(ミリ秒)

# --- upload_videos.py: YouTube アップロード ---
DEFAULT_PRIVACY_STATUS = "public"  # 環境変数 YT_PRIVACY_STATUS で上書き可能
YOUTUBE_CATEGORY_ID = "27"  # Education
UPLOAD_MAX_RETRIES = 3
UPLOAD_RETRY_BACKOFF_SECONDS = 5
# 以前はdictionaryapi.dev(無料・認証不要の小規模なコミュニティ運営API)を
# 使っていたが、タイムアウトや5xxエラー(522=オリジンサーバーとの接続失敗、
# 等)が頻発したため、Wikimediaのインフラ上で動くWiktionaryのREST APIに
# 切り替えた。同じく無料・認証不要だが可用性が高い。レスポンス形式が異なる
# ({"en": [...]}形式)ため、パース処理はdictionary_lookup.pyに分離している。
DICTIONARY_API_URL = "https://en.wiktionary.org/api/rest_v1/page/definition/{word}"
DICTIONARY_API_TIMEOUT_SECONDS = 20
DICTIONARY_API_MAX_RETRIES = 3
DICTIONARY_API_RETRY_BACKOFF_SECONDS = 3
# WikimediaのAPI利用ポリシー(https://meta.wikimedia.org/wiki/User-Agent_policy)
# は、クライアントを識別できるUser-Agentヘッダーの送信を必須としており、
# 無い場合(Pythonのrequestsのデフォルト値等)は403 Forbiddenで拒否される。
DICTIONARY_API_HEADERS = {
    "User-Agent": "SayItRight/1.0 (https://github.com/2000Re/SayItRight)"
}

# --- compile_shorts.py: Shorts結合動画 ---
# Shorts(縦型9:16、3分以内)は本数を連結しても合計尺が短いままだと
# 縦型ゆえにYouTubeにShorts判定されてしまうため、結合時は横型(16:9)
# キャンバスにピラーボックス(左右に無地の帯)で配置し直す。
COMPILATION_STATE_PATH = "compilation_state.json"
COMPILATION_BATCH_SIZE = 10  # この件数たまるごとに結合動画を1本作る
COMPILATION_DOWNLOAD_DIR = "compilation_downloads"
COMPILATION_OUTPUT_DIR = "compilation_output"
COMPILATION_VIDEO_WIDTH = 1920
COMPILATION_VIDEO_HEIGHT = 1080
COMPILATION_BG_COLOR = (23, 19, 16)  # video_builder.BG_COLORSの一色(#171310)と統一
# 動画の削除・非公開化・著作権クレーム等で恒久的にダウンロードできない
# ケースと、一時的なネットワーク不調を区別するためのリトライ回数。
# ここで諦めた動画はcompilation_state.jsonのskipped_video_idsに記録し、
# 結合対象から永久に除外する(次回以降ダウンロードを再試行しない)。
COMPILATION_DOWNLOAD_MAX_RETRIES = 2
COMPILATION_DOWNLOAD_RETRY_BACKOFF_SECONDS = 5
