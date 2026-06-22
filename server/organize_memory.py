# エピソード記憶を追加
import chromadb
import pandas as pd
import logging
import os
import datetime
from openai import OpenAI
import argparse
import ollama
import yaml
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN

# LlamaIndex
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.embeddings.ollama import OllamaEmbedding

from preprocess_data import load_database

DB_PATH = "./chroma_db"
COLLECTION_NAME = "conversation_memory"
EM_MODEL = "embeddinggemma:300m"

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

# OpenAIクライアント (要約生成用)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

with open('prompts/user_basicinfo.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
user_name = config['basic_info']['name']


def filter_logs_by_date(df: pd.DataFrame, target_date: datetime.date) -> pd.DataFrame:
    """
    DataFrameから指定した日付のログのみを抽出
    """
    # timestamp列から日付部分のみを取り出して比較
    df_filtered = df[df['timestamp'].dt.date == target_date].copy()
    return df_filtered


def make_conversation_text(df: pd.DataFrame) -> str:
    """
    DataFrameをLLMが読みやすいテキスト形式に変換
    """
    text_log = ""
    role_name = ""
    for _, row in df.iterrows():
        # roleの表記を見やすく変換
        if row['role'] == 'user':
            role_name = "ユーザー"
        elif row['role'] == "assistant" or row['role'] == "ai":
            role_name = "ぬいぐるみ"
        content = row['text']
        
        # 空のテキストまたはシステム要約自体(type=episode)が含まれていた場合はスキップ
        if pd.isna(content) or ( 'type' in row and row['type'] == 'episode'):
            continue
            
        text_log += f"{role_name}: {content}\n"
    
    return text_log


def save_summary_to_vector_store(summary_text: str, date_str: str):
    """
    生成された要約をベクトルストアに保存し、埋め込みモデルを用いてIndexを作成
    """
    logger.info("Initializing Vector Store for saving...")
    
    try:
        # Embeddingモデル初期化
        embed_model = OllamaEmbedding(model_name=EM_MODEL)
        Settings.embed_model = embed_model

        # ChromaDBクライアント初期化
        db = chromadb.PersistentClient(path=DB_PATH)
        chroma_collection = db.get_or_create_collection(COLLECTION_NAME)
        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        
        # ベクトルストアのロード
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model
        )

        # 保存用Documentの作成
        doc = Document(
            text=summary_text,
            metadata={
                "type": "episode", # 通常会話と区別するタグ
                "date": date_str, # 日付情報
                "role": "system", # システム記憶扱い
                "timestamp": datetime.datetime.now().isoformat()
            }
        )
        index.insert(doc)
        logger.info(f"Successfully saved summary for {date_str} to Vector Store.")
        
    except Exception as e:
        logger.error(f"Failed to save summary to Vector Store: {e}")
        raise e


def date_type(date_str):
    return datetime.date.fromisoformat(date_str)

def main():
    arg_parser = argparse.ArgumentParser()
    # 日付指定オプションの定義
    arg_parser.add_argument("-d", "--date",
                            default=datetime.datetime.now().date(),
                            help="Target date (YYYY-MM-DD). Default is today.",
                            type=date_type)
    # オプション引数の取得
    args = arg_parser.parse_args()
    date = args.date

    logger.info("--- Start organizing memory ---")
    
    # 全ログ取得
    full_df = load_database()
    if full_df is None or full_df.empty:
        logger.warning("Database is empty.")
        return

    # 日付設定(処理実行日)
    date_str = date.strftime('%Y-%m-%d')
    logger.info(f"Processing logs for date: {date_str}")

    # 今日の分だけフィルタリング
    daily_df = filter_logs_by_date(full_df, date)
    
    if daily_df.empty:
        logger.warning(f"No conversation logs found for {date_str}.")
        return
    
    logger.info(f"Found {len(daily_df)} messages for {date_str}.")

    # テキスト化
    conversation_text = make_conversation_text(daily_df)

    # LLM要約
    logger.info("Generating summary via OpenAI...")
    try:
        target_count = max(1, int(len(daily_df) / 20))
        print(f"Aim summary num: {target_count}")

        prompt=f"""
あなたは会話ログの管理システムです。
以下の人間(ユーザー)とぬいぐるみ(AI)の会話ログから、「ユーザーとぬいぐるみのエピソード記憶」に関する重要な情報を抽出してください。

# 制約事項
1. **出力は重要度の高い順に、最大で【 {target_count} 個 】の箇条書きに厳選してください。**
2. 指定された数 ({target_count}個) を絶対に超えないでください。内容が少なくても構いません。
3. 挨拶、相槌、単純な感情表現は要約に含めないでください。
4. 会話ログ内の「〜丸」「〜村」「ラヴァル」などの誤字は「らびまる」として解釈してください。
5. その他の明らかな誤字脱字も修正して解釈してください。

# 前提情報
日付: {date_str}
ユーザー名: {user_name}
        
出力形式の例(絶対にこの内容をそのまま使用しないこと):
- {date_str}: {user_name}は来週の火曜日にゼミがあると言っていた。
- {date_str}: {user_name}一緒に好きなメロンパンの味の話をした。

※挨拶、相槌、単純な感情表現は省くこと。

ーーー以下、会話ログーーー
        """

        raw_response = ollama.generate(
            model="gemma3:12b-it-qat", 
            prompt=f"{prompt}\n{conversation_text}", 
            options={
                'temperature': 0.2, # 0.7だと例をそのまま使う　0.8は場合による
                'num_ctx': 40000, # コンテキストウィンドウ
                'repeat_penalty': 1.2
            }
        )
        summary_result = raw_response['response']
        
        # summary_result = response.output_text
        logger.info(f"Summary Result:\n{summary_result}")

        if summary_result and "なし" not in summary_result:
            for line in summary_result.splitlines():
                if line:
                    save_summary_to_vector_store(line, date_str)
        else:
            logger.info("Summary result was empty or invalid.")

        # 6. 結果の保存
        # if summary_result and "なし" not in summary_result:
        #     save_summary_to_vector_store(summary_result, date_str)
        # else:
        #     logger.info("Summary result was empty or invalid.")

    except Exception as e:
        logger.error(f"Error during summarization or saving: {e}")

    logger.info("--- Finish organizing memory ---")

if __name__ == "__main__":
    main()