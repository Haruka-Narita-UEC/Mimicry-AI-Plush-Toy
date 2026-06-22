"""
台本とチュートリアルに関する状態を管理するクラス
"""
import re
import os
import yaml
import ollama
from llama_index.llms.openai import OpenAI

SCRIPT_PATH = "prompts/tutorial_script.yaml"
BASICINFO_PATH = "prompts/user_basicinfo.yaml"

class TutorialManager:
    def __init__(self, llm: OpenAI, script_path: str = SCRIPT_PATH, basicinfo_path: str = BASICINFO_PATH):
        self.step = 0
        self.user_name = None
        self.is_finished = False
        self.llm = llm
        self.script_path = script_path
        self.basicinfo_path = basicinfo_path

        # yamlファイルから台本データ読み込み
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Scenario file not found: {script_path}")
        
        with open(script_path, 'r', encoding='utf-8') as f:
            self.script = yaml.safe_load(f)

        self._check_existing_user()


    def _check_existing_user(self):
        """
        YAMLを見て、名前が既に登録済みならチュートリアルをスキップ扱いに設定
        """
        if os.path.exists(self.basicinfo_path):
            try:
                with open(self.basicinfo_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                
                existing_name = data.get("basic_info", {}).get("name")
                
                # 名前が入っていれば、最初から finished にする
                if existing_name:
                    print(f"User name '{existing_name}' found. Skipping tutorial (Auto Mode).")
                    self.user_name = existing_name
                    self.is_finished = True
                else:
                    print("No user name found. Starting tutorial mode (Auto Mode).")

            except Exception as e:
                print(f"Error checking user info: {e}")


    def get_cur_response(self) -> str:
        """
        接続時に発話内容(step0)を取得
        """
        if self.script and self.step == 0:
            return self.script[0]["text"]
        return ""
    
    async def process_input(self, user_text: str) -> str:
        """
        ユーザー入力に対する返答生成・ステップ進行
        """
        if self.is_finished:
            return None
        
        cur_script_idx = self.step

        # シナリオ終了判定
        if cur_script_idx > len(self.script):
            self.is_finished = True
            return None
        
        scenario = self.script[cur_script_idx]
        response_text = ""

        # ユーザーの名前返答時
        if scenario["type"] == "extract_name":
            extract_name = await self._extract_name(user_text)
            self.user_name = extract_name

            self._save_name(extract_name)

            response_text = scenario["template"].format(name=extract_name)
        elif scenario["type"] == "input_name":
            response_text = scenario["template"].format(name=self.user_name)
        else:
            response_text = scenario["text"]

        self.step += 1

        if self.step > len(self.script) - 1:
            self.is_finished = True

        return response_text
    

    def load_name_from_yaml(self):
        """
        user_basicinfo.yaml から名前を読み込んで設定する
        """
        try:
            if os.path.exists(self.basicinfo_path):
                with open(self.basicinfo_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                
                # basic_info -> name の順で取得
                existing_name = data.get("basic_info", {}).get("name")
                
                if existing_name:
                    self.user_name = existing_name
                    print(f"Loaded existing user name from YAML: {self.user_name}")
                    return True
            else:
                print("Basic info file not found.")

        except Exception as e:
            print(f"Error loading name from yaml: {e}")
        
        return False


    def _save_name(self, name:str):
        """
        抽出した名前をyamlファイルに書き込む
        """
        try:
            if os.path.exists(self.basicinfo_path):
                with open(self.basicinfo_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {}

            if "basic_info" not in data:
                data["basic_info"] = {}

            if data["basic_info"] is None:
                data["basic_info"] = {}

            print(f"Updating YAML name: {data.get('basic_info', {}).get('name',)} -> {name}")
            data['basic_info']['name'] = name

            with open(self.basicinfo_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

            print("Successfully updated user_basicinfo.yaml")

        except Exception as e:
            print(f"Error updating yaml: {e}")


    async def _extract_name(self, text: str) -> str:
        """
        テキストから名前をひらがなで抽出
        """

        prompt = f"""
        以下のユーザーの発言から、ユーザーの名前を抜き出し、必ず「ひらがな」のみで出力してください。
        敬称(くん、さん)は不要です。
        名前が明示されていない場合は「あなた」と出力してください。
        余計な文章は一切含めず、名前だけを返してください。

        発言: {text}
        名前: 
        """

        try:
            response = await self.llm.acomplete(prompt)
            name = str(response).strip()
            name = re.sub(r'[！!。、\n]', '', name)
            print(f"Name extracted: {name}")
            return name
        except Exception as e:
            print(f"Name extraxtion failed: {e}")
            return "あなた"
