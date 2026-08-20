"""
candidates.json の各単語について、
  1. ARPAbet(CMU辞書由来) → IPA変換
  2. SSMLの<phoneme>タグに埋め込み、発音をTTSに保証させる
  3. Google Cloud Text-to-Speech API を呼び出して音声ファイル(mp3)を生成

を行う。1単語につき「ゆっくり読み」と「通常速度読み」の2種類を生成する
(学習コンテンツとして分かりやすくするため)。

前提:
  - 環境変数 GOOGLE_APPLICATION_CREDENTIALS_JSON に、
    GCPサービスアカウントキー(JSON)の中身をそのまま文字列で渡す
    (GitHub Secretsに登録し、ワークフロー内でファイルに書き出して使う)
  - pip install google-cloud-texttospeech
"""

import io
import json
import os
import time

from google.cloud import texttospeech
from mutagen.mp3 import MP3
from pydub import AudioSegment

from arpabet_to_ipa import arpabet_to_ipa
from config import (
    CANDIDATES_PATH,
    AUDIO_DIR as OUTPUT_DIR,
    SPEAKING_RATES,
    VOICE_NAME,
    LANGUAGE_CODE,
    MIN_EXPECTED_AUDIO_SECONDS as MIN_EXPECTED_SECONDS,
    TTS_MAX_RETRIES as MAX_RETRIES,
    TTS_RETRY_BACKOFF_SECONDS as RETRY_BACKOFF_SECONDS,
    AUDIO_PAD_MS as PAD_MS,
)

# Google Cloud TTS(特にNeural2/WaveNet系)は、エラーを返さないまま
# 音声が途中で切れる「サイレント途切れ」を起こすことが報告されている。
# そのため生成後に長さをチェックし、短すぎる場合はリトライする(しきい値は config.py)。
#
# 前後に付与する無音の長さ(PAD_MS)について: SSMLの<break>はTTSエンジン内部の
# 処理なので「サイレント途切れ」の影響を受けうるが、音声データに後付けする
# 無音はTTSを経由しないため確実に反映される。


def build_ssml(word: str, ipa: str) -> str:
    """<phoneme>タグでIPA発音を固定したSSMLを組み立てる。
    ipaが空(変換に失敗した)場合は通常のテキスト読み上げにフォールバックする。

    前後に無音(break)を入れて再生時間を確保する。
    Google Cloud TTSが生成する1秒未満のmp3は、duration情報を
    正しく認識できないプレーヤーがあり「再生できない」ことがあるため。
    """
    if ipa:
        word_ssml = f'<phoneme alphabet="ipa" ph="{ipa}">{word}</phoneme>'
    else:
        word_ssml = word
    # 先頭に300ms、単語間に800ms、末尾に500msの間を入れる
    # (単語 → 間 → もう一度単語、で聞き取りやすくしつつ、
    #  全体の再生時間を確保してプレーヤー互換性を上げる)
    return (
        '<speak>'
        '<break time="300ms"/>'
        f'{word_ssml}'
        '<break time="800ms"/>'
        f'{word_ssml}'
        '<break time="500ms"/>'
        '</speak>'
    )


def synthesize(client: texttospeech.TextToSpeechClient, ssml: str, rate: float) -> bytes:
    synthesis_input = texttospeech.SynthesisInput(ssml=ssml)
    voice = texttospeech.VoiceSelectionParams(
        language_code=LANGUAGE_CODE,
        name=VOICE_NAME,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=rate,
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content


def get_mp3_duration_seconds(audio_bytes: bytes) -> float:
    """mp3バイト列から再生時間(秒)を取得する。壊れている場合は0を返す。"""
    try:
        mp3 = MP3(io.BytesIO(audio_bytes))
        return mp3.info.length
    except Exception as e:
        print(f"    警告: mp3の長さ取得に失敗 ({e})。壊れたファイルの可能性。")
        return 0.0


def add_silence_padding(audio_bytes: bytes, pad_ms: int = PAD_MS) -> bytes:
    """mp3バイト列の前後に無音(pad_ms ミリ秒)を追加して書き出す。
    TTSエンジンを経由しない後処理なので、SSMLのbreakより確実に効く。"""
    segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    silence = AudioSegment.silent(duration=pad_ms)
    padded = silence + segment + silence
    buf = io.BytesIO()
    padded.export(buf, format="mp3")
    return buf.getvalue()


def synthesize_with_retry(
    client: texttospeech.TextToSpeechClient, ssml: str, rate: float, label: str
) -> bytes:
    """音声生成し、長さが異常に短い場合や一時的なAPIエラーの場合はリトライする。
    Google Cloud TTSはエラーを返さないまま音声が途中で切れる既知の不具合報告が
    あるため、生成後に長さで検証する。また、レート制限やサービス一時断などの
    例外も同じリトライ対象に含める(即座に単語を諦めないようにするため)。"""
    last_audio = b""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            audio = synthesize(client, ssml, rate)
        except Exception as e:
            last_error = e
            print(f"    [{label}] 生成{attempt}回目: エラー({e})。リトライします。")
            time.sleep(RETRY_BACKOFF_SECONDS)
            continue
        duration = get_mp3_duration_seconds(audio)
        if duration >= MIN_EXPECTED_SECONDS:
            return audio
        print(f"    [{label}] 生成{attempt}回目: 長さ{duration:.2f}秒(異常に短い)。リトライします。")
        last_audio = audio
        time.sleep(RETRY_BACKOFF_SECONDS)
    if last_audio:
        print(f"    [{label}] {MAX_RETRIES}回試しても正常な長さになりませんでした。最後の結果を使用します。")
        return last_audio
    print(f"    [{label}] {MAX_RETRIES}回試してもエラーが解消しませんでした。")
    raise last_error


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    if not candidates:
        print("candidates.json が空です。音声生成をスキップします。")
        return

    client = texttospeech.TextToSpeechClient()

    for c in candidates:
        word = c["word"]
        arpabet = c["arpabet"]
        ipa = arpabet_to_ipa(arpabet)
        ssml = build_ssml(word, ipa)

        print(f"生成中: {word}  (IPA: {ipa})")

        # 1単語の処理で例外(API側の一時的な障害や認証エラーなど)が起きても、
        # ここで止めずに他の単語の処理とワークフロー後続ステップ
        # (create_videos.py / upload_videos.py / コミット)を継続させる。
        # 音声ファイルが欠けた単語は create_videos.py 側で自動的にスキップされ、
        # used_words.json にも登録されないため、次回また候補に上がる。
        try:
            for label, rate in SPEAKING_RATES.items():
                audio = synthesize_with_retry(client, ssml, rate, label)
                padded_audio = add_silence_padding(audio)
                duration = get_mp3_duration_seconds(padded_audio)
                out_path = os.path.join(OUTPUT_DIR, f"{word.lower()}_{label}.mp3")
                with open(out_path, "wb") as out_f:
                    out_f.write(padded_audio)
                print(f"  -> {out_path} ({duration:.2f}秒、前後{PAD_MS/1000:.0f}秒無音付き)")
        except Exception as e:
            print(f"[Error] {word} の音声生成に失敗しました: {e}")
            continue

    print(f"全{len(candidates)}語の音声生成が完了しました。")


if __name__ == "__main__":
    main()