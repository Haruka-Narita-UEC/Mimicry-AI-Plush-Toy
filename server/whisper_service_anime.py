"""
文字起こし用FastAPIサーバーを立てる
"""
import uvicorn
from fastapi import FastAPI, UploadFile, File
import asyncio
import uuid
import os

from transformers import pipeline
import torch

import datetime
import numpy as np

app = FastAPI()

# Whisperモデルをロード
device = "cuda" if torch.cuda.is_available() else "cpu"
# device = "cuda"
dtype = torch.float16 if device == "cuda" else torch.float32
batch_size = 64 if device == "cuda" else 4

print("Loading Whisper model...")
# GPU使用時
pipe = pipeline(
    "automatic-speech-recognition",
    model="litagin/anime-whisper",
    device=device,
    dtype=dtype, # 公式例ではtorch.float16
    chunk_length_s=30.0,
    batch_size=batch_size, # CPUの場合は1や4の方が速い可能性があります
)

generate_kwargs = {
    "language": "Japanese",
    "no_repeat_ngram_size": 0,
    "repetition_penalty": 1.0,
}

print("Whisper model loading completed!")


# ===== モデルのウォームアップ =====

print("Warming up Whisper model...")
try:
    # 1秒間の無音データを作成
    dummy_audio = np.zeros(16000, dtype=np.float32)
    
    # ダミー推論実行
    pipe(dummy_audio, generate_kwargs=generate_kwargs)
    print("Whisper warmup completed!")
except Exception as e:
    print(f"Whisper warmup failed: {e}")

# ===== ウォームアップ終了 =====



@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    音声ファイルを受け取り、文字起こし結果を返すエンドポイント
    """
    # 一時ファイルとして保存
    temp_filename = f"user_voice/uservoice_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    try:
        # アップロードされたファイルの内容を読み取って一時ファイルに書き込む
        with open(temp_filename, "wb") as f:
            f.write(await file.read())
        
        print(f"Received audio for whisper: {temp_filename}")

        result = await asyncio.to_thread(
            pipe,
            temp_filename,
            generate_kwargs=generate_kwargs
        )

        transcribed_text = result["text"].strip()

        if transcribed_text[0] == '…':
            print(f"Original whisper S2T result: {transcribed_text}")
            transcribed_text = transcribed_text[1:]

        print(f"Whisper S2T result: {transcribed_text}")
        
        # 結果をJSONで返す
        return {"status": "success", "text": transcribed_text}

    except Exception as e:
        print(f"Error in Whisper service: {e}")
        return {"status": "error", "text": str(e)}
    
    finally:
        pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)