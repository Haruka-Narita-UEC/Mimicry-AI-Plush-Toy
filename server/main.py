"""
チュートリアル用中心処理
"""
import uvicorn
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import traceback
import websockets.exceptions
import requests
import re
import argparse

import ack_loader
import text_processor
import rag
import tutorial_scenario
import browser_viewer
from tutorial_scenario import TutorialManager

import datetime
import time

# app = FastAPI()
app = FastAPI(lifespan=rag.lifespan)

app.include_router(browser_viewer.router)

# サービスのエンドポイント
WHISPER_SERVICE_URL = "http://localhost:8001/transcribe"
TTS_SERVICE_URL = "http://localhost:5000/voice"

LLM_ERROR_OUTPUT = "…すみません！もう1回お願いします！"

CURRENT_LANGUAGE = "JP"
# TTS_MODEL = "init_model2"
# TTS_MODEL = "01_narita_merge"
# TTS_MODEL = "02_narita_merge"
TTS_MODEL = "03_narita_merge"

FORCED_MODE = "auto"

start = time1 = time2 = time3 = time4 = 0.0

battery = 10

def check_battery_alert(data: bytes) -> str | None:
    """
    受信バイナリデータが数字(バッテリー残量)ならば返答テキスト、そうでなければNoneを返す
    """
    # 音声データ(数KB以上)は無視
    if len(data) > 100:
        return None

    try:
        message = data.decode('utf-8').strip() # 文字列変換
        
        if message.isdigit(): # 数字のみで構成されているかチェック
            level = int(message)
            if level < battery :
                battery = level
                print(f"Low battery detected: {level}%")
                return f"元気、「{level}」パーセントだよぉ…"
            else:
                return None
    except Exception:
        pass # デコードエラー等は無視
        
    return None

async def tts_and_send(websocket: WebSocket, text: str, lang: str):
    """
    テキストをTTSサーバーに送り、返ってきた音声をWebSocketでクライアントに送信する
    """
    if not text:
        return
    
    sentences = text_processor.split_sentences(text)
    print(f"Streaming TTS: {len(sentences)} sentences found.")

    try:
        print(f"Start VC (Calling TTS Service)... Text: {text}")
        time2 = time.perf_counter()

        for idx, sent in enumerate(sentences):
            if not sent.strip():
                continue
            
            print(f"Processing Sentence {idx+1}/{len(sentences)}: {sent}")
            
            # TTSパラメータ
            data_vc = {
                'text': sent, 
                'encoding': 'utf-8', 
                'model_name': TTS_MODEL,
                'model_id': 0, 
                'speaker_name': TTS_MODEL,
                'sdp_ratio' : 0.5, 
                'noise': 0.6, 
                'noisew': 0.8, 
                'language': lang,
                'split_interval': 0.1, 
                'style_weight': 5
            } 

            # TTSサービス呼び出し
            # TTS生成中もクライアント側は前の音声を再生しているため、並列性が生まれる
            response_vc = await asyncio.to_thread(requests.post, TTS_SERVICE_URL, params=data_vc)
            response_vc.raise_for_status()
            wave_bytes = response_vc.content

            # PCM処理
            pcm_bytes = wave_bytes[44:] 
            if len(pcm_bytes) % 2 != 0:
                pcm_bytes = pcm_bytes[:-1]

            # 送信
            print(f"Sending PCM chunk size: {len(pcm_bytes)}")
            await websocket.send_text("START_OF_AUDIO") # 文ごとの開始合図
            await asyncio.sleep(0.05) 

            CHUNK = 1024 * 8 
            for i in range(0, len(pcm_bytes), CHUNK):
                await websocket.send_bytes(pcm_bytes[i:i+CHUNK])
                await asyncio.sleep(0.01)

            await websocket.send_text("END_OF_AUDIO") # 文ごとの終了合図
            print(f"Sentence {idx+1} sent.")
            
            # 次の文への遷移用待機（必要に応じて調整）
            await asyncio.sleep(0.05)

        # 全ての文の送信完了を通知
        await websocket.send_text("END_OF_RESPONSE")
        time3 = time.perf_counter()
        print('T2S Time: {:.2f}'.format(time3-time2))
        print("All sentences sent. Signal END_OF_RESPONSE.")

    except Exception as e:
        print(f"Error in TTS/Send process: {e}")
        traceback.print_exc()
        raise e


@app.websocket("/ws") # /wsでWebSocket接続を受け付ける
async def websocket_endpoint(websocket: WebSocket): # WebSocket接続が合った時に呼び出される関数
    await websocket.accept() # クライアントからの接続を許可
    print(f"Client connected: {websocket.client}")

    from llama_index.core.settings import Settings

    tutorial_mgr = TutorialManager(llm=Settings.llm)

    if FORCED_MODE == "tutorial":
        print("MODE: TUTORIAL")
        tutorial_mgr.is_finished = False
        tutorial_mgr.step = 0
        tutorial_mgr.user_name = None
    elif FORCED_MODE == "normal":
        print("FORCE MODE: NORMAL")
        tutorial_mgr.is_finished = True
        tutorial_mgr.load_name_from_yaml()
        
        # 読み込めなかった場合
        if not tutorial_mgr.user_name:
            print("Warning: Name not found in YAML. Using default.")
            tutorial_mgr.user_name = "ユーザー"

    try:
        # モードをクライアントに通知
        if not tutorial_mgr.is_finished:
            # チュートリアルモード通知
            await websocket.send_text("MODE_TUTORIAL")
            print("Sent MODE_TUTORIAL signal.")
        else:
            # 通常モード通知
            await websocket.send_text("MODE_NORMAL")
            print("Sent MODE_NORMAL signal.")
            # ユーザーへの挨拶
            greeting = f"あっ！{tutorial_mgr.user_name}さん！"
            await tts_and_send(websocket, greeting, CURRENT_LANGUAGE)
        
        # 接続時に一度だけメッセージを送信
        await websocket.send_text("{\"status\": \"connected\", \"text\": \"Server connected. Touch screen.\"}")
        print("------------------------------")

        while True: # クライアントに接続している間
            # 音声データをバイナリとして受信
            wav_data = await websocket.receive_bytes()

            start = time.perf_counter()
            output = ""

            battery_alert = check_battery_alert(wav_data)

            if battery_alert:
                output = battery_alert
                await websocket.send_text("{\"status\": \"battery_alert_received\"}")

            # "SHAKE" 信号の検知
            try:
                message = wav_data.decode('utf-8').strip()
                if message == "SHAKE":
                    print("Received SHAKE signal.")
                    # チュートリアル中かつStep0なら開始
                    if not tutorial_mgr.is_finished and tutorial_mgr.step == 0:
                        print("Triggering Step 0 from Shake...")
                        step0_text = tutorial_mgr.get_cur_response()
                        await tts_and_send(websocket, step0_text, CURRENT_LANGUAGE)
                        await browser_viewer.manager.broadcast(step0_text)
                        
                        tutorial_mgr.step += 1
                    else:
                        print("Shake ignored (Not in Step 0 or Tutorial finished).")
                    
                    # SHAKE処理後は音声認識へ進まずループ先頭へ
                    continue 
            except Exception:
                # デコードに失敗した場合は通常の音声データとみなして続行
                pass

            await websocket.send_text("{\"status\": \"received\"}")
            print(f"\nReceived audio data: {len(wav_data)} bytes")

            try:
                print("Start S2T (Calling Whisper Service)...")
                    
                # Whisperサービス呼び出し
                # ファイルデータを 'files' 引数で送信
                files = {'file': ('audio.wav', wav_data, 'audio/wav')}
                data_payload = {'lang': CURRENT_LANGUAGE}
                response = await asyncio.to_thread(requests.post, WHISPER_SERVICE_URL, files=files, data=data_payload)
                response.raise_for_status()
                result = response.json()

                result = response.json()
                if result.get("status") != "success":
                    raise Exception(f"Whisper service error: {result.get('text')}")
                
                transcribed_text = result.get("text", "")
                print(f"S2T result: {transcribed_text}")
                time1 = time.perf_counter()
                print('Transcribe Time: {:.2f}'.format(time1-start))

                if tutorial_mgr.is_finished:
                # 相槌の送信
                    ack_filepath, ack_pcm_bytes = ack_loader.get_ack(transcribed_text, CURRENT_LANGUAGE)
                    if ack_pcm_bytes:
                        await ack_loader.send_ack(websocket, ack_filepath, ack_pcm_bytes)
                        time1_5 = time.perf_counter()
                        print('ACK Time from receiving audio: {:.2f}'.format(time1_5 - start))
                
                await websocket.send_text("{\"status\": \"processing\", \"text\": \"Thinking...\"}")

                is_volume_command = False
                
                if "音量" or "声" in transcribed_text:
                    if any(w in transcribed_text for w in ["上げ", "大きく", "大きい", "アップ"]):
                        print("Command: Volume UP")
                        await websocket.send_text("VOL_UP") # クライアントへコマンド送信
                        # output = "はい、音量を上げました。" # ユーザーへの返答
                        is_volume_command = True
                        
                    elif any(w in transcribed_text for w in ["下げ", "小さく", "小さい", "ダウン"]):
                        print("Command: Volume DOWN")
                        await websocket.send_text("VOL_DOWN") # クライアントへコマンド送信
                        # output = "はい、音量を下げました。" # ユーザーへの返答
                        is_volume_command = True

                if len(transcribed_text) == 0:
                    output = LLM_ERROR_OUTPUT
                else:
                    if not tutorial_mgr.is_finished:
                        # チュートリアルモード
                        print("Mode: Tutorial")

                        script_response = await tutorial_mgr.process_input(transcribed_text)

                        if script_response:
                            output = script_response

                            if tutorial_mgr.user_name and "さんですね" in output:
                                print(f"Injecting user name into memory: {tutorial_mgr.user_name}")

                                memory_text = f"- {format(datetime.date.today(), '%Y-%m-%d')}: ユーザーと出会った。ユーザーの名前は{tutorial_mgr.user_name}。"
                                rag.add_memory_to_idx(memory_text, "system")
                        else: # チュートリアル終了直後(仮でRAGへ移行)
                            print("Tutorial finished! Switching to RAG.")
                            response_obj = await rag.chat_engine.achat(transcribed_text)
                            output = str(response_obj)
                    else:
                        print("Mode: Normal RAG")
                        response_obj = await rag.chat_engine.achat(transcribed_text)
                        output = str(response_obj)

                        output = await text_processor.check_llm_output(websocket, output, CURRENT_LANGUAGE)

                        if output == "Empty Response":
                            output = LLM_ERROR_OUTPUT
                        else:
                            is_broken = len(output) > 200 and "えーとね、えーとね、" in output # 簡易的な判定ロジック
    
                            if not is_broken:
                                # STT結果を記憶に追加
                                rag.add_memory_to_idx(transcribed_text, 'user')
                                # LLM結果を記憶に追加
                                rag.add_memory_to_idx(output, 'assistant')
                            else:
                                print("Warning: Broken response detected. Not saving to memory.")

                        target_chars = "[！。？]"
                        output = re.sub(f"({target_chars})", r"\1\n", output)

                print(f"LLM output: {output}")
                time2 = time.perf_counter()
                print('LLM Time: {:.2f}'.format(time2-time1))

                if output:
                    await tts_and_send(websocket, output, lang=CURRENT_LANGUAGE)
                    await browser_viewer.manager.broadcast(output)

                time4 = time.perf_counter()
                print('TOTAL TIME: {:.2f}\n'.format(time4-start))
                print("------------------------------")
            
            except Exception as e:
                print(f"Processing Error: {e}")
                traceback.print_exc()


    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosedError) as e: # receive_bytesを待機中、または内側からraiseされた切断
        print(f"Client disconnected: {websocket.client} ({e})")

    except Exception as e: # その他の予期せぬエラー
        print(f"An unexpected error occurred in websocket handler: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    # 引数の取得
    parser = argparse.ArgumentParser(description="Voice Assistant Server")
    parser.add_argument(
        "--lang", 
        type=str, 
        default="JP", 
        help="Target language code (e.g., JP, EN, ZH). Default is JP."
    )
    parser.add_argument(
        "--mode", 
        type=str, 
        default="auto", 
        choices=["auto", "tutorial", "normal"],
        help="Force operation mode: 'auto' (check yaml), 'tutorial' (force tutorial), 'normal' (force RAG)"
    )
    
    args = parser.parse_args()
    
    # グローバル変数に反映
    if args.lang != "JP":
        CURRENT_LANGUAGE = args.lang
        TTS_MODEL = "nrhrEN_1h30_20251130"
    print(f"Server starting with language mode: {CURRENT_LANGUAGE}")

    # モード設定の反映
    FORCED_MODE = args.mode
    print(f"Operation Mode: {FORCED_MODE}")

    rag.set_rag_config(CURRENT_LANGUAGE)

    # メインゲートウェイの起動
    uvicorn.run(app, host="0.0.0.0", port=8000)