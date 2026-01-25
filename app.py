
import streamlit as st
import pandas as pd
import os
import time
import asyncio
import re
from google.genai import types
from google.genai import Client

# --- Page Config ---
st.set_page_config(
    page_title="PatentInsight AI",
    page_icon="🔬",
    layout="wide"
)

# --- Authentication Logic ---
def check_password():
    """Returns `True` if the user had the correct password."""
    if "APP_PASSWORD" not in st.secrets:
        st.error("⚠️ 設定未完了: アプリのパスワード(APP_PASSWORD)が設定されていません。")
        return False

    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔒 ログイン")
        st.write("このアプリを使用するにはパスワードが必要です。")
        st.text_input("パスワード", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔒 ログイン")
        st.text_input("パスワード", type="password", on_change=password_entered, key="password")
        st.error("パスワードが間違っています。")
        return False
    else:
        return True

# --- CSS Injection (Enhanced Design) ---
REPORT_CSS = """
<style>
    /* 全体のコンテナデザイン（紙のような見た目） */
    .report-container {
        background-color: #ffffff;
        color: #1f2937;
        font-family: "Helvetica Neue", Arial, "Hiragino Kaku Gothic ProN", "Hiragino Sans", Meiryo, sans-serif;
        line-height: 1.7;
        padding: 40px;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        margin-bottom: 30px;
        border: 1px solid #e5e7eb;
    }

    /* 見出しのデザイン */
    .report-container h1 { 
        font-size: 28px; 
        font-weight: 700; 
        color: #111827; 
        border-bottom: 3px solid #2563eb; 
        padding-bottom: 15px; 
        margin-bottom: 30px; 
        margin-top: 10px; 
    }
    
    .report-container h2 { 
        font-size: 22px; 
        font-weight: 700; 
        color: #1e40af; 
        background-color: #f0f9ff; 
        padding: 12px 16px; 
        border-left: 6px solid #2563eb; 
        margin-bottom: 20px; 
        margin-top: 40px; 
        border-radius: 0 4px 4px 0;
    }
    
    .report-container h3 { 
        font-size: 19px; 
        font-weight: 700; 
        color: #374151; 
        border-bottom: 1px solid #d1d5db; 
        padding-bottom: 8px; 
        margin-bottom: 15px; 
        margin-top: 25px; 
    }

    /* 本文・リスト */
    .report-container p { 
        margin-bottom: 1.2em; 
        text-align: justify; 
        font-size: 16px;
    }
    
    .report-container ul, .report-container ol { 
        margin-bottom: 20px; 
        padding-left: 20px; 
    }
    
    .report-container li { 
        margin-bottom: 8px; 
        font-size: 16px;
    }

    /* 強調表示 */
    .report-container strong { 
        color: #1d4ed8; 
        font-weight: 700; 
        background: linear-gradient(transparent 70%, #dbeafe 70%);
    }

    /* テーブルデザイン（重要） */
    .report-container table { 
        width: 100%; 
        border-collapse: collapse; 
        margin: 25px 0; 
        font-size: 15px; 
        border: 1px solid #d1d5db;
        border-radius: 4px;
        overflow: hidden;
    }
    
    .report-container thead tr {
        background-color: #f1f5f9;
        border-bottom: 2px solid #cbd5e1;
    }
    
    .report-container th { 
        padding: 12px 15px; 
        text-align: left; 
        font-weight: 700; 
        color: #334155; 
        white-space: nowrap;
    }
    
    .report-container td { 
        padding: 12px 15px; 
        border-bottom: 1px solid #e2e8f0; 
        vertical-align: top;
        color: #4b5563;
    }
    
    .report-container tr:nth-child(even) {
        background-color: #f8fafc;
    }
    
    .report-container tr:hover {
        background-color: #f0f9ff;
    }

    /* サマリーボックス */
    .summary-box {
        background-color: #fffbeb;
        border: 1px solid #fcd34d;
        border-radius: 6px;
        padding: 20px;
        margin-bottom: 25px;
    }
</style>
"""

# --- Logic: Data Compression ---

def truncate_text(text, max_length):
    if pd.isna(text) or text == "": return ""
    s = str(text)
    return s if len(s) <= max_length else s[:max_length] + "..."

def compress_patent_row(row):
    priority_keys = ['title', 'invention', 'abstract', 'claim', 'applicant', 'number', 'publication', 'id', '発明', '名称', '要約', '請求', '出願人', '番号']
    row_dict = row.to_dict()
    sorted_items = []
    for k, v in row_dict.items():
        if pd.isna(v) or v == "": continue
        k_str = str(k).lower()
        is_priority = any(pk in k_str for pk in priority_keys)
        score = 0 if is_priority else 1
        sorted_items.append((score, k, v))
    sorted_items.sort(key=lambda x: x[0])
    
    row_string = ""
    for _, k, v in sorted_items:
        k_trunc = truncate_text(k, 30)
        v_trunc = truncate_text(v, 300)
        row_string += f"{k_trunc}: {v_trunc} | "
        if len(row_string) > 1500:
            row_string += "[TRUNCATED]"
            break
    return row_string

# --- Logic: Gemini API Interaction with Key Rotation ---

# 高速化のために軽量モデルを使用
MODEL_NAME = 'gemini-flash-lite-latest'

async def generate_with_retry(client, model, contents, config, retries=3):
    """
    リトライラッパー。Flash Liteは高速なため、バックオフ時間は短めに設定。
    """
    base_delay = 5 
    for attempt in range(retries):
        try:
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    raise Exception(f"API制限(429)により中断: {error_str}")
            else:
                raise e

async def analyze_batch(client, rows_text, focus_keywords, exclude_keywords, batch_index, total_batches):
    """
    バッチ分析タスク
    """
    prompt = f"""
    あなたは特許分析の専門家です。
    大規模な特許調査の一部（Batch {batch_index + 1}/{total_batches}）を担当しています。
    以下の特許データを分析し、中間分析レポートを作成してください。

    ### ユーザーの着目点
    {focus_keywords or "特になし"}

    ### 除外条件
    {exclude_keywords or "特になし"}

    ### 出力内容
    1. **技術クラスター**: このバッチ内の主な技術トピック。
    2. **重要特許**: 注目すべき特許の抽出（公報番号、出願人、理由）。
    3. **出願人**: 目立つ出願人。

    ### データ
    {rows_text}
    """
    try:
        response = await generate_with_retry(
            client=client,
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Analyze the patent batch objectively."
            )
        )
        return response.text or ""
    except Exception as e:
        return f"Error in batch {batch_index}: {str(e)}"

async def generate_final_report(clients, data_frames, focus_keywords, exclude_keywords):
    """
    マルチクライアント・並列処理対応の生成ロジック
    """
    total_rows = len(data_frames)
    compressed_rows = [compress_patent_row(row) for _, row in data_frames.iterrows()]
    
    CHUNK_SIZE = 60 
    
    if total_rows <= CHUNK_SIZE:
        # --- Single Pass ---
        status_text = f"全{total_rows}件を一括分析中 (Model: {MODEL_NAME})..."
        yield status_text
        
        data_string = "\n---\n".join(compressed_rows)
        client = clients[0]

        prompt = f"""
          あなたは熟練した特許弁理士です。
          提供された特許リストを元に「特許調査レポート」を作成してください。
          
          ### ユーザー指定の条件
          - **着目キーワード**: {focus_keywords or "全体的な技術トレンド"}
          - **除外対象**: {exclude_keywords or "特になし"}

          ### レポート構成（HTML形式）
          必ず純粋なHTMLタグで出力してください（Markdownの ```html ... ``` は不要です）。
          
          1. **全体総括**: 
             - 全体的な所感、トレンド。
             - `<div class="summary-box">` タグを使って、要約を囲ってください。
             
          2. **重要特許 (Top Picks)**: 
             - `<table>`タグを使用して整理。
             - ヘッダーは `<thead>`, ボディは `<tbody>` を使用。
             
          3. **技術カテゴリ別詳細**: トピックごとの解説。

          ### データ
          {data_string}
        """

        response = await generate_with_retry(
            client=client,
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Output raw HTML only. Use <table> for patent lists."
            )
        )
        yield clean_html(response.text)
        
    else:
        # --- Map-Reduce Strategy (Parallel) ---
        chunks = []
        for i in range(0, total_rows, CHUNK_SIZE):
            chunks.append(compressed_rows[i : i + CHUNK_SIZE])
        
        total_chunks = len(chunks)
        yield f"大規模データ分析を開始: 全{total_chunks}バッチを並列処理します..."
        
        tasks = []
        for i, chunk in enumerate(chunks):
            client_index = i % len(clients)
            assigned_client = clients[client_index]
            chunk_text = "\n---\n".join(chunk)
            
            tasks.append(
                analyze_batch(assigned_client, chunk_text, focus_keywords, exclude_keywords, i, total_chunks)
            )

        batch_summaries = [""] * total_chunks
        completed_count = 0
        
        async def run_task_with_index(idx, coro):
            return idx, await coro

        wrapped_tasks = [run_task_with_index(i, t) for i, t in enumerate(tasks)]
        
        for future in asyncio.as_completed(wrapped_tasks):
            idx, result = await future
            batch_summaries[idx] = result
            completed_count += 1
            yield f"進捗: {completed_count}/{total_chunks} バッチ完了..."

        combined_summaries = "\n\n".join([f"--- Batch {i+1} Report ---\n{s}" for i, s in enumerate(batch_summaries)])
        
        yield "全バッチ完了。最終レポートを生成中..."
        
        final_client = clients[0] 
        
        final_prompt = f"""
          あなたは特許分析の専門家です。
          以下は、大規模データを分割分析した「中間レポート」の集合です。
          これらを統合し、最終的な「特許調査レポート」を作成してください。

          ### ユーザー指定の条件
          - **着目キーワード**: {focus_keywords or "全体的な技術トレンド"}
          - **除外対象**: {exclude_keywords or "特になし"}

          ### レポート構成（HTML形式）
          必ず純粋なHTMLタグで出力してください（Markdownの ```html ... ``` は不要です）。

          1. **全体総括**: 
             - トレンド分析。
             - `<div class="summary-box">` タグを使って、特に重要な要約を囲ってください。
             
          2. **重要特許ピックアップ**: 
             - 必ずHTMLの `<table>`, `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` タグを使用。
             
          3. **技術カテゴリ別詳解**: 解説。

          ### 中間レポート集合
          {combined_summaries}
        """

        response = await generate_with_retry(
            client=final_client,
            model=MODEL_NAME,
            contents=final_prompt,
            config=types.GenerateContentConfig(
                system_instruction="Output raw HTML only. No markdown fences. Use <table> for lists."
            )
        )
        yield clean_html(response.text)

def clean_html(text):
    if not text: return ""
    
    # 1. コードブロック (```html ... ``` or ``` ...) を強力に除去
    # 正規表現: ```(任意の文字)``` の中身を取り出す、もしくは ```自体を消す
    
    # パターン1: コードブロックの中身を抽出する試み
    # re.DOTALL は改行を含むすべての文字にマッチさせる
    code_block_match = re.search(r"```(?:html)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block_match:
        cleaned_text = code_block_match.group(1)
    else:
        # コードブロックがない場合は、そのまま使うが、念のためバッククォートだけは消す
        cleaned_text = text.replace("```html", "").replace("```", "")
        
    # 2. 余分な空白の除去
    return cleaned_text.strip()

# --- Main Application ---

def main():
    if not check_password():
        st.stop()

    st.sidebar.title("🔬 PatentInsight AI")
    st.sidebar.caption("Speed & Bulk Edition")
    
    # --- API Key Loading Logic (Enhanced) ---
    raw_api_keys = []
    
    candidate_keys = ["API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"]
    for i in range(1, 11):
        candidate_keys.append(f"API_KEY_{i}")
        candidate_keys.append(f"GOOGLE_API_KEY_{i}")
    
    for key_name in candidate_keys:
        val = os.environ.get(key_name)
        if val: raw_api_keys.append(val)

    if "API_KEYS" in st.secrets:
        val = st.secrets["API_KEYS"]
        if isinstance(val, list):
            raw_api_keys.extend(val)
    
    try:
        for key, val in st.secrets.items():
            if isinstance(val, str) and val.strip().startswith("AIza"):
                raw_api_keys.append(val)
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v.strip().startswith("AIza"):
                        raw_api_keys.append(v)
    except Exception:
        pass

    valid_api_keys = []
    seen = set()
    for k in raw_api_keys:
        k_clean = k.strip()
        if k_clean and k_clean not in seen and k_clean.startswith("AIza") and "ここに" not in k_clean:
            seen.add(k_clean)
            valid_api_keys.append(k_clean)
    
    if not valid_api_keys:
        st.sidebar.error("⛔ API Key Missing")
        st.error("⚠️ APIキーが見つかりません。")
        st.stop()
    
    st.sidebar.success(f"🔑 {len(valid_api_keys)}個のAPIキーを認識")
    
    clients = [Client(api_key=k) for k in valid_api_keys]

    st.sidebar.markdown("---")
    uploaded_file = st.sidebar.file_uploader("Excelファイルをアップロード", type=['xlsx', 'xls', 'xlsm'])
    focus_keywords = st.sidebar.text_area("着目テーマ・キーワード", height=100)
    exclude_keywords = st.sidebar.text_area("除外・スキップ条件", height=80)

    st.title("特許調査レポート生成 (Fast Mode)")
    st.markdown(f"""
    Excelデータをアップロードすると、AIが内容を分析してレポートを作成します。
    **現在のモデル:** `{MODEL_NAME}` (高速・軽量版)
    **並列処理:** 有効 (キー数: {len(clients)})
    """)

    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            st.success(f"ファイル読み込み完了: {len(df)}件のデータ")
            
            if st.button("分析開始 (Start Analysis)", type="primary"):
                result_container = st.empty()
                progress_bar = st.progress(0)
                
                async def run_analysis():
                    final_html = ""
                    step = 0
                    async for chunk in generate_final_report(clients, df, focus_keywords, exclude_keywords):
                        step += 1
                        if len(chunk) < 200:
                            result_container.info(chunk)
                        else:
                            final_html = chunk
                    return final_html

                html_content = asyncio.run(run_analysis())
                
                progress_bar.progress(100)
                result_container.empty()
                
                if html_content:
                    st.markdown("### 生成レポート")
                    
                    # HTMLの注入（デザインクラスを適用したDivで囲む）
                    full_html = f"{REPORT_CSS}<div class='report-container'>{html_content}</div>"
                    st.markdown(full_html, unsafe_allow_html=True)
                    
                    import streamlit.components.v1 as components
                    js_code = f"""
                    <script>
                    function copyReport() {{
                        const content = `{html_content.replace('`', '\`').replace('$', '\$')}`;
                        navigator.clipboard.writeText(content).then(function() {{
                            alert('コピー完了');
                        }}, function(err) {{
                            console.error('Copy failed: ', err);
                        }});
                    }}
                    </script>
                    <div style="text-align: right; margin-top: 10px;">
                        <button onclick="parent.document.execCommand('selectAll'); parent.document.execCommand('copy'); alert('レポートを選択しました。Ctrl+C (MacはCmd+C) でコピーしてください。');" 
                        style="background-color: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 14px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        📋 全選択してコピー (OneNote貼付用)
                        </button>
                    </div>
                    """
                    components.html(js_code, height=100)

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")

if __name__ == "__main__":
    main()
