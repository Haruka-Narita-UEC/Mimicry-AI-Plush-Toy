"""
相槌処理の管理
"""
import glob
# from openai import OpenAI # api
import ollama # local
from fastapi import WebSocket
import asyncio
import time
# import os # api

ACK_FOLDER_PATH = "ack_wav"
CURRENT_LANGUAGE = "JP"

MODEL = 'gemma3n:e4b'

def load_ack_audio(filepath: str) -> bytes:
    try:
        with open(filepath, "rb") as f:
            wave_bytes = f.read()
        
            pcm_bytes = wave_bytes[44:] # ヘッダ削除

            # データ長が奇数の場合、最後の1バイトを削り偶数に
            if len(pcm_bytes) % 2 != 0:
                pcm_bytes = pcm_bytes[:-1]

        return pcm_bytes
    
    except FileNotFoundError:
        print(f"Warning: {filepath} not found.")
        return b""
    
    except Exception as e:
        print(f"Error loading ack audio {filepath}: {e}")
        return b""

prompt = """
あなたは、ユーザーの入力タイプを分類するAIです。
以下のルールに従い、分類結果の数字【0, 1, 2, 3, 4, 5】のいずれか一つだけを、**数字のみ**で出力してください。

- ルール:
- 0: あいさつ (例: おはよう, こんにちは), 不満, 呼びかけ
- 1: 感謝, 評価 (例: ありがとう, すごい)
- 2: 依頼, 招待, 提案 (例: 〜してください, 〜しませんか)
- 3: 情報提供 (単なる事実や意見)
- 4: 3と同じ (情報提供)
- 5: 質問 (例: 〜ですか？, なぜ？)

- 上記に当てはまらない場合: 1

--- 以下、入力文 ---

"""

# # api
# client = OpenAI( 
#     api_key=os.environ["OPENAI_API_KEY"],
# )

def get_ack(input: str, lang: str=CURRENT_LANGUAGE):

    if not input:
        return None, None # inputが空の時はNoneを返す
    
    CURRENT_LANGUAGE = lang
    
    start = time.perf_counter()

    # # api
    # response = client.responses.create( 
    #     model="gpt-4.1-nano-2025-04-14",
    #     instructions=prompt,
    #     input=input,
    # )

    # local
    response = ollama.generate(model=MODEL, prompt=prompt + input)

    print(f"Ack LLM output: {response['response']}")

    # time1 = time.perf_counter()
    # print('LLM responce to ACK Time: {:.2f}'.format(time1-start))

    # api
    # if response.output_text.isdecimal() == False or int(response.output_text) < 0 or int(response.output_text) > 5:
    #     ack_num = 0
    # else:
    #     ack_num = int(response.output_text)

    # local
    # if response['response'].isdecimal() == False or int(response['response']) < 0 or int(response['response']) > 5:
    #     ack_num = 0
    # else:
    #     ack_num = int(response['response'])
    
    # Ollamaの返答を文頭から見て、半角数字を見つけたら終了し変数に格納
    ack_num = next((char for char in response['response'] if '0' <= char <= '9'), None)
    if not ack_num: # 見つからない場合は0
        ack_num = 0

    print(f"ack number: {ack_num}")

    ack_filepath = glob.glob(f'{ACK_FOLDER_PATH}_{CURRENT_LANGUAGE}/{ack_num}*.wav')

    if not ack_filepath:
        print("Warning: ackpath not found.")
        return None, None # ファイルパス読み込み失敗時はNoneを返す
    
    pcm_bytes = load_ack_audio(ack_filepath[0])
    
    return ack_filepath[0], pcm_bytes


def get_additional_ack():
    ack_num = 5
    ack_filepath = glob.glob(f'{ACK_FOLDER_PATH}_{CURRENT_LANGUAGE}/{ack_num}*.wav')

    if not ack_filepath:
        print("Warning: Additional ackpath not found.")
        return None, None # ファイルパス読み込み失敗時はNoneを返す
    
    pcm_bytes = load_ack_audio(ack_filepath[0])
    
    return ack_filepath[0], pcm_bytes


async def send_ack(websocket: WebSocket, ack_filepath: str, ack_pcm_bytes):
    if ack_pcm_bytes:
        print("Sending acknowledgment audio...")
        await websocket.send_text("START_OF_ACK")

        print(f"ack path: {ack_filepath}")
        
        CHUNK = 1024 * 8 # 15KBずつ送信
        for i in range(0, len(ack_pcm_bytes), CHUNK):
            await websocket.send_bytes(ack_pcm_bytes[i:i+CHUNK])
            await asyncio.sleep(0.01) # 短い待機

        await websocket.send_text("END_OF_ACK")
        print("Acknowledgment audio sent.")


async def warmup_ack():
    """サーバー起動時にOllamaを叩き起こすためのダミー関数"""
    try:
        dummy_prompt = prompt + "こんにちは"
        await asyncio.to_thread(ollama.generate, model=MODEL, prompt=dummy_prompt)
    except Exception as e:
        print(f"Ack warmup error: {e}")
                    