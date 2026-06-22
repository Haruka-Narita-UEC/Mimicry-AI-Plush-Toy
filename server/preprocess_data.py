import chromadb
import pandas as pd
import json
import logging
import os
from typing import List
import datetime

DB_PATH = "./chroma_db" # データセットのパス
COLLECTION_NAME = "conversation_memory" # コレクション名

OUTPUT_PATH = f"jsonl_log/log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl" # jsonlファイル出力先
REV_OUTPUT_PATH = f"jsonl_dataset/dataset_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl" # jsonlファイル出力先
APPEND_MODE = True # 既存のデータセットに追記する(True)または毎回上書きする(False)

TASK_SYSTEM_PROMPT = "You are an assistant who accurately mimics the way your conversation partner (the user) speaks, their style, and their personality. Respond as the user would." # 使わないかも

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)


def load_database():
    """
    ChromaDBから会話ログを取得
    """
    logger.info(f"Connecting to ChromaDB '{DB_PATH}'...")
    try:
        client = chromadb.PersistentClient(path=DB_PATH)
        collection = client.get_collection(name=COLLECTION_NAME)

    except Exception as e:
        logger.error(f"Failed to connect to ChromaDB or to get collection '{COLLECTION_NAME}': {e}")
        logger.error("Check that rag.py has been executed and the database has been initialized.")
        return None

    logger.info("Geting all logs from the collection...")
    try:
        # includeに"documents"(本文)と"metadatas"(role, timestamp)を指定
        logs = collection.get(include=["documents", "metadatas"])
        
        if not logs['ids']:
            logger.warning("No documents found otherwise the collection exists.")
            return None
            
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")
        return None

    # データをDataFrameに変換
    try:
        df = pd.DataFrame({
            'id': logs['ids'],
            'text': logs['documents'],
            'metadata': logs['metadatas']
        })
        
        # メタデータ辞書を個別カラムに展開
        meta_df = pd.json_normalize(df['metadata'])
        df = pd.concat([df.drop(columns=['metadata']), meta_df], axis=1)

        # print(df)
        
        if 'timestamp' not in df.columns or 'role' not in df.columns:
            logger.error("No 'timestamp' or 'role' found in metadata.")
            logger.error(f"Detected column: {df.columns.tolist()}")
            logger.error("Check that main.py/rag.py is saving logs with the correct metadata.")
            return None
            
        # タイムスタンプでソート
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values(by='timestamp').reset_index(drop=True)
        
        logger.info(f"A total of {len(df)} log entries were retrieved and sorted.")
        return df

    except Exception as e:
        logger.error(f"Error in conversion to Dataframe: {e}")
        return None


def reverse_dataset(df: pd.DataFrame) -> List[dict]:
    """
    役割を反転した会話ペアのリストを作成
    """
    dataset_entries: List[dict] = []
    
    for i in range(len(df) - 1):
        current_entry = df.iloc[i]
        next_entry = df.iloc[i+1]
        
        # 連続したai->userのペアを見つける
        if current_entry['role'] == 'assistant' and next_entry['role'] == 'user':
            
            ai_speech = current_entry['text']
            user_speech = next_entry['text']
            
            # 空のメッセージはスキップ
            if not ai_speech or not user_speech:
                continue
                
            entry = {
                "messages": [
                    {"role": "user", "content": ai_speech},
                    {"role": "assistant", "content": user_speech}
                ]
            }
            dataset_entries.append(entry)
            
    logger.info(f"{len(dataset_entries)} valid “user->assistant” conversation pair has been extracted.")
    return dataset_entries


def noreverse_dataset(df: pd.DataFrame) -> List[dict]:
    """
    会話ペアのリストを作成
    """
    dataset_entries: List[dict] = []
    
    for i in range(len(df) - 1):
        current_entry = df.iloc[i]
        next_entry = df.iloc[i+1]
        
        # 連続したai->userのペアを見つける
        if current_entry['role'] == 'user' and next_entry['role'] == 'assistant':
            
            user_speech = current_entry['text']
            ai_speech = next_entry['text']
            
            # 空のメッセージはスキップ
            if not ai_speech or not user_speech:
                continue
                
            entry = {
                "messages": [
                    {"role": "user", "content": user_speech},
                    {"role": "assistant", "content": ai_speech}
                ]
            }
            dataset_entries.append(entry)
            
    return dataset_entries


def save_dataset(dataset: List[dict], filepath: str, append: bool):
    """
    データセットをJSONLファイルに保存する
    """
    write_mode = 'a' if append and os.path.exists(filepath) else 'w'
    
    try:
        with open(filepath, write_mode, encoding='utf-8') as f:
            for entry in dataset:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        action = "appended" if write_mode == 'a' else "created"
        logger.info(f"The dataset has been {action} to '{filepath}'.")
        
    except IOError as e:
        logger.error(f"Failed to save file '{filepath}': {e}")


def main():
    logger.info("--- Start preprocess of training LLM ---")
    
    # ChromaDBから会話ログ取得
    conversation_df = load_database()
    
    if conversation_df is None or conversation_df.empty:
        logger.warning("No conversation logs found.")
        return

    # データセット作成
    training_dataset = noreverse_dataset(conversation_df)
    # 役割反転データセット作成
    training_dataset_rev = reverse_dataset(conversation_df)
    
    if not training_dataset or not training_dataset_rev:
        logger.warning("No train data found.")
        return

    # jsonlファイル保存
    save_dataset(training_dataset, OUTPUT_PATH, append=APPEND_MODE)
    save_dataset(training_dataset_rev, REV_OUTPUT_PATH, append=APPEND_MODE)
    
    logger.info("--- Finish preprocess ---")


if __name__ == "__main__":
    main()