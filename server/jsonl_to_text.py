import json

def jsonl_to_txt(input_path: str):
    format_text = ""

    try:
        with open(input_path, "r", encoding='utf-8') as f:
            for i, line in enumerate(f):
                format_text += load_jsonline(line)

    except FileNotFoundError:
        return "Error: Jsonl file not found."
    except json.JSONDecodeError:
        return "Error: Json format is not correct."
    
    return format_text
                    

def load_jsonline(line: str):
    data = json.loads(line)
    messages = data.get("messages", [])

    text = "----- Conversation Data -----\n"

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "user":
            speaker = "ユーザー"
        elif role == "assistant":
            speaker = "ぬいぐるみ"
        else:
            speaker = role

        text += f"{speaker}: {content}\n"

    text += "\n"

    return text