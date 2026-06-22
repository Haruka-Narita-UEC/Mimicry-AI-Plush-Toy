"""
RAG入力前LLM出力テキストの最適化(文の数・文字数・マークダウン)
"""
from openai import OpenAI
import ack_loader
from fastapi import WebSocket
import os
import re


def cut_texts(text: str, max_sentence: int=3, char_limit_at_second: int=60, lang: str="JP") -> str:
    target_chars = set("。！？.!?")
    bracket_pairs = {"「":"」", "（": "）", "(": ")"}
    if lang == "EN":
        char_limit_at_second = 120
    elif lang == "ZH":
        char_limit_at_second = 50

    bracket_stack = []
    count = 0 # 文末記号のカウント
    is_target_before = False # 直前が文末記号か

    for i, char in enumerate(text): # textを先頭から確認

        # 1. 括弧判定
        if char in bracket_pairs.keys(): # 開き括弧の場合
            bracket_stack.append(bracket_pairs[char]) # 対応する閉じ括弧をスタックにプッシュ
            is_target_before = False
            continue

        if bracket_stack and char == bracket_stack[-1]: # 閉じ括弧の場合
            bracket_stack.pop() # 対応する正しい閉じ括弧の場合はスタックからポップ
            is_target_before = False
            continue

        if bracket_stack: # 括弧の中にいる場合(文末判定をスキップ)
            continue
        
        # 2. 文末判定
        if char in target_chars: # 文末記号の場合
            if not is_target_before: # 直前が文末記号ではない場合
                count +=1

                is_limit = count == max_sentence
                is_long = (count == 2 and i > char_limit_at_second)

                if is_limit or is_long: # 文数か文字数が制限に達した場合
                    return text[:i+1]
            
            is_target_before = True
        else: # 括弧内でも文末でもない場合
            is_target_before = False
            
    return text


def split_sentences(text: str) -> list[str]:
    """
    テキストを句読点(。！？)で分割してリストで返す
    分割後も句読点は維持
    """
    parts = re.split(r'([。！？.!?]+)', text)
    
    sentences = []
    current_sentence = ""
    
    for part in parts:
        current_sentence += part
        if re.search(r'[。！？.!?]', part):
            sentences.append(current_sentence.strip())
            current_sentence = ""
    
    # 余った部分があれば追加
    if current_sentence.strip():
        sentences.append(current_sentence.strip())
        
    return sentences


def check_markdown(text: str, lang: str):
    if lang == "EN":
        target_chars = "*:"
    else:
        target_chars = "-*.:"
    for i, char in enumerate(text): # textを先頭から確認
        if char in target_chars: # i番目の文字charが上記記号の場合
            return True
        
    return False


def remove_markdown(text):
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
    )

    prompt = "入力された文章を、**言語は入力言語のままで**、マークダウン(リスト、番号付きリスト)を使わない簡潔な話し言葉に変換してください。"

    response = client.responses.create(
        model="gpt-4.1-nano-2025-04-14",
        instructions=prompt,
        input=text,
    )
    output = response.output_text

    print("Removed markdown from output.")
    return output


def remove_tag(text: str):
    pattern = r"^\[.*?\] "
    text_removed = re.sub(pattern, "", text, flags=re.MULTILINE)
    return text_removed


async def check_llm_output(websocket: WebSocket, text: str, lang: str="JP"):
    if check_markdown(text, lang):
        ack_filepath, ack_pcm_bytes = ack_loader.get_additional_ack()
        await ack_loader.send_ack(websocket, ack_filepath, ack_pcm_bytes)
        text = remove_markdown(text)

    text = cut_texts(text=text, lang=lang)
    text = remove_tag(text)
    text = text.replace('\n', '')

    return text