from jsonl_to_text import jsonl_to_txt
import ollama
import yaml
import datetime
import re
import argparse

PROMPT_PATH = "prompts/prompt_extract_basicinfo.txt"
MODEL = "gemma3:12b-it-qat"

def extract_basicinfo(conversation_txt: str):
    try:
        with open(PROMPT_PATH, 'r', encoding='utf-8') as f:
            extract_prompt = f.read()
    except FileNotFoundError:
        print(f'Waring: {PROMPT_PATH} cannot be read.')
        exit()

    prompt = f"""
    {extract_prompt}

    #################
    【会話ログ】
    {conversation_txt}
    #################
    """

    print("Extracting basic info...")
    response = ollama.generate(
        model=MODEL, 
        prompt=prompt, 
        options={
            'temperature': 0.2, 
            'num_ctx': 128000, # コンテキストウィンドウ
            'repeat_penalty': 1.2
        }
    )
    raw_response = response['response']

    print("Raw response:", raw_response)
    return raw_response


def remove_codeblock(raw_response: str):
    # コードブロック(```yaml ... ```)がある場合は中身だけ取り出す
    match = re.search(r'```yaml\n(.*?)\n```', raw_response, re.DOTALL)
    if match:
        yaml_text = match.group(1)
    else: # yamlタグがない場合でも```で囲まれている場合
        match_generic = re.search(r'```\n(.*?)\n```', raw_response, re.DOTALL)
        if match_generic:
            yaml_text = match_generic.group(1)
        else:
            yaml_text = raw_response
    
    return yaml_text


def save_dict_yaml(yaml_text: str, raw_response: str):
    # 文字列を辞書型(dict)として読み込む
    try:
        data_dict = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        print("YAML Parse Error:", e)
        data_dict = None

    # 辞書型として保存する
    if isinstance(data_dict, dict):
        filename = f"extract_yaml/extract_basicinfo_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.yaml"
        with open(filename, mode='w', encoding='utf-8') as f:
            # dict を渡すことで、正しく構造化されたYAMLファイルになります
            yaml.safe_dump(data_dict, f, allow_unicode=True, sort_keys=False)
        print(f"Saved to {filename}")
    else:
        print("Error: The response could not be parsed as a dictionary.")
        # デバッグ用に生のテキストを保存
        with open("debug_failed_parse.txt", "w", encoding="utf-8") as f:
            f.write(raw_response)


def main():
    parser = argparse.ArgumentParser(description="Extract Basic Info from JSONL")
    parser.add_argument("-l", "--log", required=True, help="Timestamp for log JSONL file (e.g. 20260112_112609)")
    args = parser.parse_args()

    jsonl_file_path = f"jsonl_log/log_{args.log}.jsonl"
    print(f"Log File: {jsonl_file_path}")

    conversation_log = jsonl_to_txt(jsonl_file_path)
    response = extract_basicinfo(conversation_log)
    yaml_txt = remove_codeblock(response)
    save_dict_yaml(yaml_txt, response)

if __name__ == "__main__":
    main()
