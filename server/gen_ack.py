# 相槌音声の作成
import asyncio
import traceback
import requests
import argparse

TTS_SERVICE_URL = "http://localhost:5000/voice"

ACK_MAP = {
    'JP': ("うん、", "うんうん、", "えっとー、", "そっかー、", "なるほどね、", "んーっとね、"),
    'EN': ("Aha, ", "Yeah, ", "Uh-huh, ", "I see, ", "Right, ", "Mmhmm, "),
    'ZH': ("嗯，", "嗯嗯，", "那个…，", "这样啊，", "原来如此，", "这个嘛…，")
}

default_model = "nrhr6h_nojp_20251121"

async def tts_and_send(text: str, lang: str="JP", model: str="nrhr6h_nojp_20251121"):
    if not text:
        return

    try:
        print(f"Start VC (Calling TTS Service)... Text: {text}")
        # time2 = time.perf_counter()

        # TTSパラメータ
        data_vc = {
            'text': text, 
            'encoding': 'utf-8', 
            'model_name': model,
            'model_id': 0, 
            'speaker_name': model,
            'sdp_ratio' : 0.5, 
            'noise': 0.6, 
            'noisew': 0.8, 
            'length': 0.8,
            'language': lang,
            'split_interval': 0.1, 
            'style_weight': 5
        }  
        # TTSサービス呼び出し
        response_vc = await asyncio.to_thread(requests.post, TTS_SERVICE_URL, params=data_vc)
        response_vc.raise_for_status()
        # レスポンスのコンテント(WAVバイナリ)を取得
        wave_bytes = response_vc.content

        return wave_bytes

    except Exception as e:
        print(f"Error in TTS/Send process: {e}")
        traceback.print_exc()
        raise e

async def main():
    parser = argparse.ArgumentParser(description="Generate acknowledgements audio.")
    parser.add_argument("-m", "--model", type=str, default=default_model, help="Style-Bert-VITS2 model name to generate acknowledgements.")
    parser.add_argument("--lang", type=str, default="JP", help="Target language code (e.g., JP, EN, ZH). Default is JP."
    )
    args = parser.parse_args()

    model = args.model
    lang = args.lang

    # model = ["nrhr6h_nojp_20251121", "nrhrEN_few_20251127", "nrhrZH_few_20251127"]
    # model = ["nrhrEN_1h30_20251130"]

    for i, text in enumerate(ACK_MAP[lang]):
        wave_bytes = await tts_and_send(text, lang, model)
        with open(f"ack_wav_{lang}/{i}_{text}.wav", "wb") as f:
            f.write(wave_bytes)

    # wave_bytes = await tts_and_send(text_dict["JP"], "JP", "nrhr6h_20251121")
    # with open("output_" + "JP" + "_extra.wav", "wb") as f:
    #     f.write(wave_bytes)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExit program.")