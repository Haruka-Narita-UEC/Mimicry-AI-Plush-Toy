"""
LLM・埋め込みモデルの管理
プロンプトと短期記憶の管理
"""
import chromadb
from fastapi import FastAPI
from contextlib import asynccontextmanager

from llama_index.core import Document
import datetime
import traceback
import os
import asyncio
import requests

import ack_loader # ウォームアップ用

from llama_index.core import VectorStoreIndex, ServiceContext, StorageContext
from llama_index.core.settings import Settings
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding

from llama_index.core.chat_engine.condense_plus_context import CondensePlusContextChatEngine
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.base.llms.generic_utils import messages_to_history_str

from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.chat_engine.types import ChatMode
from llama_index.core.storage.chat_store import SimpleChatStore

from llama_index.llms.openai import OpenAI

# Ollama Embedding設定
EM_MODEL = "embeddinggemma:300m"

API_KEY = os.environ["OPENAI_API_KEY"] # api

CONFIG_MAP = {
    'JP': {
        'model': "gpt-4.1-nano-2025-04-14",
        'initprompt_path': 'prompts/initprompt_20251120.txt'
    },
    'EN': {
        'model': "gpt-4.1-nano-2025-04-14",
        'initprompt_path': 'prompts/initpromptE_20251120.txt'
    },
    'ZH': {
        'model': "gpt-4.1-nano-2025-04-14",
        'initprompt_path': 'prompts/initpromptE_20251120.txt'
    }
}

query_engine = None
index = None
chat_engine = None

USER_PERSONA_PATH = 'prompts/user_persona.yaml'
USER_BASICINFO_PATH = 'prompts/user_basicinfo.yaml'
SYSTEM_RULES_PATH = 'prompts/system_rules.txt'


def set_rag_config(lang: str):
    global CURRENT_LANG
    if lang in CONFIG_MAP:
        CURRENT_LANG = lang
    else:
        CURRENT_LANG = "JP"

class HybridChatEngine(CondensePlusContextChatEngine):
    def __init__(self, **kwargs):
        self._condense_llm = kwargs.pop("condense_llm", None)
        super().__init__(**kwargs)

    async def _acondense_question(self, chat_history, latest_message):
        if not self._condense_llm:
            return await super()._acondense_question(chat_history, latest_message)
        
        chat_history_str = messages_to_history_str(chat_history)

        prompt = self._condense_prompt_template.format(
            chat_history=chat_history_str,
            question=latest_message
        )

        print("Running Condense Query on Local LLM...")
        response = await self._condense_llm.acomplete(prompt)
        return str(response)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # サーバー起動時
    global chat_engine, index

    print("Triggered Lifespan!")

    current_config = CONFIG_MAP.get(CURRENT_LANG, CONFIG_MAP["JP"])
    model_id = current_config["model"]

    # (A)システムルールの読み込み 
    try:
        with open(SYSTEM_RULES_PATH, 'r', encoding='utf-8') as f:
            rules_text = f.read()
    except FileNotFoundError:
        print(f"Warning: {SYSTEM_RULES_PATH} not found. Using default rules.")
        rules_text = "あなたは元気なぬいぐるみです。短く返答してください。"

    # (B)ユーザー基本情報の読み込み
    try:
        with open(USER_BASICINFO_PATH, 'r', encoding='utf-8') as f:
            basic_info_text = f.read()
    except FileNotFoundError:
        print(f"Warning: {USER_BASICINFO_PATH,} not found. Using No basin info.")
        basic_info_text = "基本情報なし"

    # (C)ユーザーペルソナ(性格・話し方)の読み込み
    try:
        with open(USER_PERSONA_PATH, 'r', encoding='utf-8') as f:
            persona_text = f.read()
    except FileNotFoundError:
        print(f"Warning: {USER_PERSONA_PATH} not found. Using No persona.")
        persona_text = "ペルソナ情報なし"

    today = format(datetime.date.today(), '%Y-%m-%d')

    # (D)結合して最終的なシステムプロンプトを作成
    SYSTEM_PROMPT = f"""
{rules_text}

### User Basic Information (Reference Only)
ユーザーに関する事実情報です。会話の中で自然に活用してください。
{basic_info_text}

### User Personality Profile (Target Persona)
これは「ユーザーの性格」の分析データですが、あなたはこれを参考に
「ユーザーの波長に合うような話し方」や「共感」を行ってください。
{persona_text}

### Today's date
{today}
"""

    print(f"System Prompt Loaded. Length: {len(SYSTEM_PROMPT)} chars")

    # ChromaDBクライアント初期化
    db = chromadb.PersistentClient(path="./chroma_db")
    chroma_collection = db.get_or_create_collection("conversation_memory")
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    main_llm = OpenAI(
        api_key=API_KEY, 
        model=model_id,
        temperature=0.7, # 創造性のバランス(0.7程度が会話向き)
        presence_penalty=0.6, # 既に出たトークンを使いにくくする(ループ防止)
        frequency_penalty=0.5 # 同じ単語の頻出を抑える
    )
    # embed_model = OpenAIEmbedding(api_key=API_KEY, model=EM_MODEL) # api

    condense_llm = Ollama(
        model="gemma3n:e4b",
        request_timeout=30.0,
        temperature=0.0
    )

    # Ollama Embedding初期化
    embed_model = OllamaEmbedding(EM_MODEL) # local

    # LlamaIndexの定義
    Settings.llm = main_llm
    Settings.embed_model=embed_model

    # dbが空かどうかで読み込み方を変更
    db_count = chroma_collection.count()

    if db_count == 0: # dbが空の場合
        dummy_doc = Document( # 初期ドキュメントの作成
            text = "Conversation History Start.",
            metadata = {
                "role": "system",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        index = VectorStoreIndex.from_documents(
            [dummy_doc],
            storage_context = storage_context,
            embed_model = embed_model
        )
    else:
        # ベクトルストアのロード
        index = VectorStoreIndex.from_vector_store(
            vector_store,
            embed_model = embed_model
        )

    # 永続化チャットストア(短期記憶用)
    chat_store = SimpleChatStore.from_persist_path("./conversation_chat_store.json")

    CONTEXT_TEMPLATE = """
    Here is some background information from our past conversation (Memory):
    ---------------------
    {context_str}
    ---------------------

    Using the memory above (only if relevant) and the system rules, respond to user.
    User's latest input follows below."""

    # EN・ZHの場合はここを翻訳するかchat_mode=ChatMode.CONTEXTにする
    CONDENSE_QUESTION_PROMPT = """
    以下は、ユーザーとAIアシスタントの会話履歴です。
    この履歴と最新のユーザー入力を踏まえて、検索エンジンに入力するための
    「文脈を含んだ独立した質問文」を日本語で作成してください。
    
    <Chat History>
    {chat_history}
    
    <Follow Up Input>
    {question}
    
    <Standalone question>
    """

    memory = ChatMemoryBuffer.from_defaults(
        token_limit=3000,
        chat_store=chat_store
    )

    chat_engine = HybridChatEngine.from_defaults(
        retriever=index.as_retriever(similarity_top_k=2),
        llm=main_llm,
        condense_llm=condense_llm,
        chat_mode=ChatMode.CONDENSE_PLUS_CONTEXT,
        memory=memory,
        system_prompt=SYSTEM_PROMPT,
        context_template=CONTEXT_TEMPLATE,
        condense_question_prompt=CONDENSE_QUESTION_PROMPT, # ChatMode.CONTEXTの場合は不要
        verbose=True
    )

    print("--- RAG Pipeline Initialized ---")

    # ===== モデルのウォームアップ =====
    
    print("Warming up LLM/Embedding/Ack models...")

    try:
        # 1. Embedding
        await asyncio.to_thread(embed_model.get_text_embedding, "Warm up query") # ダミーテキストを埋め込み化してキャッシュへ
        print("  - Embedding model warmed up.")

        # 2. LLM
        await main_llm.acomplete("これはテストです。'OK'とだけ返してください。") # 直接LLMを使用して会話履歴(Memory)を汚さない
        print("  - Main LLM warmed up.")
        
        # 3. 相槌用LLM(Ollama)
        await ack_loader.warmup_ack() 
        print("  - Ack LLM warmed up.")

        # 4. Style-Bert-VITS2
        tts_url = "http://localhost:5000/voice"
        
        # ダミーパラメータ
        dummy_tts_params = {
            'text': 'あ',
            'encoding': 'utf-8', 
            'model_name': 'nrhr6h_20251121',
            'speaker_name': 'nrhr6h_20251121',
            'language': 'JP',
            'model_id': 0
        }
        
        await asyncio.to_thread(requests.post, tts_url, params=dummy_tts_params) # 受取不要
        print("  - TTS Service warmed up.")

    except Exception as e:
        print(f"Warmup failed: {e}")
        traceback.print_exc()
    
    print("All systems ready!")

    # ===== ウォームアップ終了 =====

    yield
    chat_store.persist(persist_path="./conversation_chat_store.json")
    print("--- RAG Pipeline Shutting Down ---")


def add_memory_to_idx(text_context: str, speaker: str):
    if index is None:
        print("Error: RAG index is not initialized. Memory not added.")
        return
    
    try:
        # LlamaIndexのDocumentオブジェクトを作成
        doc = Document(
            text = text_context,
            metadata = {
                "role": speaker, # 'user' or 'assistant'
                "timestamp": datetime.datetime.now().isoformat()
            }
        )
        index.insert(doc)
        print(f"Mermory added: {text_context}")
    except Exception as e:
        print(f"Error adding memory: {e}")
        traceback.print_exc()