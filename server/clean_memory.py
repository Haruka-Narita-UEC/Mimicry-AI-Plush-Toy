import chromadb
import logging
import os
import shutil
import argparse
import datetime

# 設定
DB_PATH = "./chroma_db"
COLLECTION_NAME = "conversation_memory"

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

def backup_database():
    """DBフォルダ全体をバックアップ"""
    backup_path = f"{DB_PATH}_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if os.path.exists(DB_PATH):
        if os.path.exists(backup_path):
            shutil.rmtree(backup_path) # 既存のバックアップがあれば削除
        shutil.copytree(DB_PATH, backup_path)
        logger.info(f"Backup created at: {backup_path}")
    else:
        logger.warning(f"Database path {DB_PATH} does not exist.")


def get_ids_by_date(collection, target_date_str: str):
    """
    指定された日付(文字列)に一致するデータのIDリストを取得
    メタデータの timestamp が target_date_str で始まるものを対象とする
    """
    logger.info("Scanning for records...")
    
    try:
        # 全データのメタデータとIDのみを取得（軽量化のためdocumentsは取得しない）
        results = collection.get(include=["metadatas"])
        
        if not results or not results['ids']:
            return []

        ids_to_delete = []
        
        for i, meta in enumerate(results['metadatas']):
            # timestampキーが存在し、かつ入力された日付で始まっているか確認
            # 例: "2023-12-01 10:00:00" startswith "2023-12-01" -> True
            if meta and 'timestamp' in meta and (meta["role"] == 'user' or meta["role"] == "assistant"):
                ts = str(meta['timestamp'])
                if ts.startswith(target_date_str):
                    ids_to_delete.append(results['ids'][i])
                    
        return ids_to_delete
    
    except Exception as e:
        logger.error(f"Error during search: {e}")
        return []
    

def remove_init_document(collection):
    """
    rag.py で作成された初期ダミー("Conversation History Start.")のみを削除
    """
    logger.info("Scanning for initial dummy document...")
    
    try:
        # roleがsystemのものだけを取得。テキスト内容を確認するため documents も取得する
        results = collection.get(
            where={"role": "system"},
            include=["metadatas", "documents"]
        )

        if not results or not results['ids']:
            logger.info("No system documents found.")
            return

        ids_to_delete = []
        target_text = "Conversation History Start."

        for i, doc_text in enumerate(results['documents']):
            meta = results['metadatas'][i]
            
            # 条件1: テキストが初期ドキュメントと完全一致するか
            is_match_text = (doc_text == target_text)
            
            # 条件2: 'type' メタデータが存在しない、または 'episode' ではない
            is_not_episode = ('type' not in meta) or (meta['type'] != 'episode')

            if is_match_text and is_not_episode:
                logger.info(f"Found init document: ID={results['ids'][i]}, Text='{doc_text}'")
                ids_to_delete.append(results['ids'][i])

        if ids_to_delete:
            backup_database()
            collection.delete(ids=ids_to_delete)
            logger.info(f"Successfully deleted {len(ids_to_delete)} initial dummy document(s).")
        else:
            logger.info("Initial dummy document not found (or already deleted).")

    except Exception as e:
        logger.error(f"Error during init document deletion: {e}")
    

def clean_database(target_date: datetime.date):
    date_str = target_date.strftime('%Y-%m-%d')
    logger.info(f"Connecting to ChromaDB '{DB_PATH}'...")
    try:
        client = chromadb.PersistentClient(path=DB_PATH)
        collection = client.get_collection(name=COLLECTION_NAME)
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        return
    
    # 削除対象のIDを検索
    delete_ids = get_ids_by_date(collection, date_str)
    # 削除前の件数確認
    count = len(delete_ids)

    if count == 0:
        logger.info(f"No raw conversation logs found for {date_str}.")
        check_remaining_data(collection)
        return
    
    logger.info(f"Found {count} records to delete for {date_str}.")

    # バックアップを取ってから削除を実行
    backup_database()

    # 削除処理
    try:
        collection.delete(ids=delete_ids)
        logger.info(f"Successfully deleted {count} records.")
        
        # 結果確認
        remaining_count = collection.count()
        logger.info(f"Total documents remaining in DB: {remaining_count}")
        
    except Exception as e:
        logger.error(f"Error during deletion: {e}")
    
    # 残っているデータの内訳を確認(オプション)
    check_remaining_data(collection)
    # remaining = collection.get(include=["metadatas"])
    # if remaining['ids']:
    #     roles = [m.get('role', 'unknown') for m in remaining['metadatas']]
    #     from collections import Counter
    #     logger.info(f"Remaining data breakdown: {Counter(roles)}")


def check_remaining_data(collection):
    remaining = collection.get(include=["metadatas"])
    if remaining['ids']:
        roles = [m.get('role', 'unknown') for m in remaining['metadatas']]
        from collections import Counter
        logger.info(f"Remaining data breakdown: {Counter(roles)}")
    else:
        print("No data found with 'ids'.")


def date_type(date_str):
    return datetime.date.fromisoformat(date_str)

def main():
    arg_parser = argparse.ArgumentParser(description="Delete raw logs for a specific date after backup.")
    # 日付指定オプションの定義
    arg_parser.add_argument("-d", "--date",
                            default=datetime.datetime.now().date(),
                            help="Target date (YYYY-MM-DD). Default is today.",
                            type=date_type)
    
    arg_parser.add_argument("-i", "--delete-init",
                            action="store_true",
                            help="Delete the initial 'Conversation History Start' document created by rag.py.")

    # オプション引数の取得
    args = arg_parser.parse_args()
    
    if args.delete_init:
        # 初期ドキュメント削除モード
        logger.info("--- Mode: Delete Initial Document ---")
        try:
            client = chromadb.PersistentClient(path=DB_PATH)
            collection = client.get_collection(name=COLLECTION_NAME)
            remove_init_document(collection)
            check_remaining_data(collection)
        except Exception as e:
            logger.error(f"Failed to access database for init cleanup: {e}")
    # else:
    #     # 通常の日付指定ログ削除モード
    #     logger.info(f"--- Mode: Delete Logs for {args.date} ---")
    #     clean_database(args.date)

    # 通常の日付指定ログ削除モード
    logger.info(f"--- Mode: Delete Logs for {args.date} ---")
    clean_database(args.date)

if __name__ == "__main__":
    main()