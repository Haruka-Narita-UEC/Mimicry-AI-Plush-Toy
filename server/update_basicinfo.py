import yaml
import os
import argparse
import shutil
from datetime import datetime

NEW_FILE_PATH = "prompts/user_basicinfo.yaml"

# 以下のキーは古いファイルに値があれば上書きされない
IMMUTABLE_KEYS = ["name", "gender", "birthdate"]

def merge_basic_info(old_info, new_info):
    merged = old_info.copy()

    # new_info が空またはNoneなら、そのままoldを返す
    if not new_info:
        return merged

    for key, new_val in new_info.items():
        old_val = merged.get(key)

        # 値が空(None/空リスト)の場合は何もしない(情報は削除しない)
        if new_val is None or new_val == []:
            continue

        # 不変キーの処理
        if key in IMMUTABLE_KEYS:
            # 古いデータに既に値が入っている場合は、上書きせずにスキップ
            if old_val is not None:
                print(f"[KEEP] Immutable key '{key}': Keeping '{old_val}', ignoring '{new_val}'")
                continue
            else:
                # まだ情報がない場合のみ登録
                merged[key] = new_val

        # リスト型(likes, family等)の処理 -> 結合して重複排除
        elif isinstance(new_val, list):
            current_list = old_val if isinstance(old_val, list) else []
            # セットを使って重複排除しつつマージ
            merged_list = list(dict.fromkeys(current_list + new_val))
            merged[key] = merged_list
            print(f"[MERGE] List key '{key}': {current_list} + {new_val} -> {merged_list}")

        # その他の単一項目(affiliation等) -> 新しい情報で更新
        else:
            # 値が異なるときだけ更新
            if old_val != new_val:
                print(f"[UPDATE] Key '{key}': '{old_val}' -> '{new_val}'")
                merged[key] = new_val

    return merged


def create_backup(file_path):
    """
    指定されたファイルが存在する場合、タイムスタンプ付きでバックアップを作成する
    例: prompts/user_basicinfo.yaml -> prompts/user_basicinfo_20260112_183000.yaml
    """
    if os.path.exists(file_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base, ext = os.path.splitext(file_path)
        backup_path = f"{base}_{timestamp}{ext}"
        try:
            shutil.copy2(file_path, backup_path)
            print(f"Backup created: {backup_path}")
        except IOError as e:
            print(f"Error creating backup: {e}")


def main():
    parser = argparse.ArgumentParser(description="Update User Basic Info YAML")
    parser.add_argument("-n", "--new", required=True, help="Timestamp for TODAY extract_basicinfo file (e.g. 20260112_180000)")

    args = parser.parse_args()

    # パスの構築
    old_file_path = "prompts/user_basicinfo.yaml"
    today_file_path = f"extract_yaml/extract_basicinfo_{args.new}.yaml"

    print(f"Old File: {old_file_path}")
    print(f"New File: {today_file_path}")

    # 古いファイルの読み込み
    if os.path.exists(old_file_path):
        with open(old_file_path, 'r', encoding='utf-8') as f:
            old_data = yaml.safe_load(f) or {}
    else:
        old_data = {}

    # 今日のファイルの読み込み
    if os.path.exists(today_file_path):
        with open(today_file_path, 'r', encoding='utf-8') as f:
            today_data = yaml.safe_load(f) or {}
    else:
        print(f"Error: {today_file_path} not found.")
        return

    old_root = old_data.get("basic_info", {})
    today_root = today_data.get("basic_info", {})

    merged_root = merge_basic_info(old_root, today_root)

    # 保存用の構造を作成
    merged_result = {"basic_info": merged_root}

    create_backup(NEW_FILE_PATH)

    with open(NEW_FILE_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(merged_result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        print(f"Successfully saved to {NEW_FILE_PATH}")

if __name__ == "__main__":
    main()