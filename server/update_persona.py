import yaml
import json
import random
import os
import argparse
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN

NEW_FILE_PATH = "prompts/user_persona.yaml"
ALPHA = 0.3

def extract_random_user_examples(jsonl_path, max_count=10):
    """
    JSONLファイルからユーザーの発言を抽出し、ランダムに最大max_count個返す
    """
    user_messages = []
    
    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    # "messages" リスト内の "role": "user" を探す
                    for msg in data.get("messages", []):
                        if msg.get("role") == "user":
                            content = msg.get("content")
                            if content:
                                user_messages.append(content)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        print(f"Warning: JSONL file not found at {jsonl_path}. Skipping example update.")
        return []

    # 重複排除
    user_messages = list(set(user_messages))

    # ランダム選択
    if len(user_messages) <= max_count:
        return user_messages
    else:
        return random.sample(user_messages, max_count)
    

def update_examples(merged_data, examples):
    """
    マージされたデータの 'example' フィールドを、抽出した例文で更新
    """
    try:
        if examples: # 抽出できた場合のみ更新
            if 'user_profile' in merged_data and \
               'speech_style' in merged_data['user_profile']:
                
                merged_data['user_profile']['speech_style']['example'] = examples
                print(f"Updated 'example' with {len(examples)} entries from JSONL.")
            else:
                print("Warning: Target keys (user_profile -> speech_style) not found in merged YAML.")
    except Exception as e:
        print(f"Error updating examples: {e}")
    

def merge_recursive(old_val, today_val, alpha):
    # 両方とも辞書の場合->再帰呼出し
    if isinstance(old_val, dict) and isinstance(today_val, dict):
        merged = old_val.copy()
        for k, v in today_val.items():
            if k in merged:
                merged[k] = merge_recursive(merged[k], v, alpha)
            else:
                merged[k] = v
        return merged
    
    # 数値判定(boolを除外)
    is_old_num = isinstance(old_val, (int, float)) and not isinstance(old_val, bool)
    is_today_num = isinstance(today_val, (int, float)) and not isinstance(today_val, bool)

    # 両方とも数字の場合->EMA
    if is_old_num and is_today_num:
        # EMA = alpha * 新しい値 + (1 - alpha) * 古い値
        raw_val = alpha * today_val + (1 - alpha) * old_val
        # 正確な四捨五入で整数に丸める
        dec_val = Decimal(str(raw_val)).quantize(Decimal('0'), rounding=ROUND_HALF_UP)
        
        print(f"EMA Done: {old_val} -> {int(dec_val)}")
        return int(dec_val)
    
    # それ以外(文字列、リストなど)の場合-> 新しい値で上書き
    else:
        return today_val


def update_labels(merged_data):
    """
    マージされたデータの 'labels' フィールドを、Big-Fiveスコアをもとに更新
    """
    try:
        personality = merged_data.get('user_profile', {}).get('personality', {})
        big_five_data = personality.get('big_five')
        
        if not big_five_data:
            print("Warning: 'big_five' data not found.")
            return
        
        big_five_trait = {
            'openness':          ('open to experience', 'closed to experience'),
            'conscientiousness': ('conscientious',      'unconscientious'),
            'extraversion':      ('extroverted',        'introverted'),
            'agreeableness':     ('agreeable',          'antagonistic'),
            'neuroticism':       ('neurotic',           'emotionally stable')
        }

        intensity_map = {
            0: "Neutral",
            1: "Slight",
            2: "Moderate",
            3: "Distinct",
            4: "Strong",
            5: "Extreme"
        }

        for trait, (pos, neg) in big_five_trait.items():
            if trait not in big_five_data:
                continue

            score = big_five_data[trait].get('score', 5)

            dist = int(abs(score - 5))
            if dist > 5: dist = 5

            intensity = intensity_map.get(dist, "Unknown")

            if dist == 0:
                label = intensity
            elif score > 5:
                label = f"{intensity} {pos}"
            else:
                label = f"{intensity} {neg}"

            big_five_data[trait]['label'] = label

    except Exception as e:
        print(f"Error updating labels: {e}")


def create_backup(file_path):
    """
    指定されたファイルが存在する場合、タイムスタンプ付きでバックアップを作成する
    例: prompts/user_persona.yaml -> prompts/user_persona_20260112_183000.yaml
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
    parser = argparse.ArgumentParser(description="Update User Persona YAML")
    parser.add_argument("-n", "--new", required=True, help="Timestamp for TODAY extract_persona file (e.g. 20260112_180000)")
    parser.add_argument("-l", "--log", required=True, help="Timestamp for log JSONL file (e.g. 20260112_112609)")
    args = parser.parse_args()

    # パスの構築
    old_file_path = "prompts/user_persona.yaml"
    today_file_path = f"extract_yaml/extract_persona_{args.new}.yaml"
    jsonl_file_path = f"jsonl_log/log_{args.log}.jsonl"

    print(f"Old File: {old_file_path}")
    print(f"New File: {today_file_path}")
    print(f"Log File: {jsonl_file_path}")
    
    try: 
        with open(old_file_path, 'r', encoding='utf-8') as f:
            old_data = yaml.safe_load(f)
            
        with open(today_file_path, 'r', encoding='utf-8') as f:
            today_data = yaml.safe_load(f)
    except FileNotFoundError as e:
        print(f"Error loading YAML files: {e}")
        return

    merged_result = merge_recursive(old_data, today_data, ALPHA)

    random_examples = extract_random_user_examples(jsonl_file_path, max_count=10)

    update_examples(merged_result, random_examples)
    update_labels(merged_result)

    create_backup(NEW_FILE_PATH)

    with open(NEW_FILE_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(merged_result, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


if __name__ == "__main__":
    main()