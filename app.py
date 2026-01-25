
import streamlit as st
import pandas as pd
import os
import time
import asyncio
import re
import html
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

# --- CSS Injection (Professional Document Design) ---
REPORT_CSS = """
<style>
    /* レポート全体のコンテナ（紙のような質感と読みやすい幅） */
    .report-container {
        background-color: #ffffff;
        color: #333333;
        font-family: "Hiragino Kaku Gothic Pro", "Meiryo", "Yu Gothic", "Noto Sans JP", sans-serif;
        line-height: 1.8;
        padding: 50px;
        max-width: 1000px; /* 一行が長くなりすぎないように制限 */
        margin: 0 auto 40px auto; /* 中央揃え */
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
        border: 1px solid #f0f0f0;
    }

    /* タイトルデザイン */
    .report-container h1 { 
        font-size: 32px; 
        font-weight: 800; 
        color: #1a202c; 
        border-bottom: 4px solid #3b82f6; 
        padding-bottom: 20px; 
        margin-bottom: 40px; 
        letter-spacing: 0.05em;
    }
    
    /* セクション見出し */
    .report-container h2 { 
        font-size: 24px; 
        font-weight: 700; 
        color: #1e3a8a; 
        background: linear-gradient(to right, #eff6ff, #ffffff);
        padding: 15px 20px; 
        border-left: 8px solid #2563eb; 
        margin-top: 50px; 
        margin-bottom: 25px; 
        border-radius: 4px;
    }
    
    /* 小見出し */
    .report-container h3 { 
        font-size: 20px; 
        font-weight: 700; 
        color: #4b5563; 
        border-bottom: 2px solid #e5e7eb; 
        padding-bottom: 10px; 
        margin-top: 35px; 
        margin-bottom: 20px; 
    }

    /* 本文テキスト */
    .report-container p { 
        font-size: 16px;
        margin-bottom: 1.5em; 
        text-align: justify; 
        color: #374151;
    }
    
    /* リスト */
    .report-container ul, .report-container ol { 
        margin-bottom: 25px; 
        padding-left: 25px; 
        color: #374151;
    }
    
    .report-container li { 
        margin-bottom: 10px; 
        font-size: 16px;
    }

    /* 重要キーワードのハイライト */
    .report-container strong { 
        color: #2563eb; 
        font-weight: 700; 
    }
    
    /* マーカー風ハイライト（クラス指定用） */
    .keyword-highlight {
        background: linear-gradient(transparent 60%, #bfdbfe 60%);
        font-weight: bold;
        padding: 0 4px;
    }

    /* テーブルデザイン（可読性重視） */
    .report-container table { 
        width: 100%; 
        border-collapse: separate; 
        border-spacing: 0;
        margin: 30px 0; 
        font-size: 15px; 
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.03);
    }
    
    .report-container thead tr {
        background-color: #f8fafc;
    }
    
    .report-container th { 
        padding: 15px; 
        text-align: left; 
        font-weight: 700; 
        color: #1e40af; 
        border-bottom: 2px solid #cbd5e1;
        white-space: nowrap;
    }
    
    .report-container td { 
        padding: 15px; 
        border-bottom: 1px solid #e2e8f0; 
        vertical-align: top;
        color: #475569;
        background-color: #fff;
    }
    
    .report-container tr:last-child td {
        border-bottom: none;
    }
    
    .report-container tr:hover td {
        background-color: #f0f9ff;
    }

    /* サマリーボックス */
    .summary-box {
        background-color: #fffbeb;
        border-left: 6px solid #f59e0b;
        padding: 25px;
        margin-bottom: 30px;
        border-radius: 4px;
    }
    .summary-box h2 {
        background: none;
        border: none;
        padding: 0;
        margin-top: 0;
        color: #92400e;
        margin-bottom: 15px;
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

MODEL_NAME = 'gemini-2.5-flash-lite'

async def generate_with_retry(client, model, contents, config, retries=3):
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
    total_rows = len(data_frames)
    compressed_rows = [compress_patent_row(row) for _, row in data_frames.iterrows()]
    
    CHUNK_SIZE = 60 
    
    if total_rows <= CHUNK_SIZE:
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
          **重要**: 出力は純粋なHTMLコードのみを行ってください。Markdownのコードブロック（```html）は含めないでください。
          
          1. **全体総括**: 
             - 全体的な所感、トレンド。
             - `<div class="summary-box">` タグで囲ってください。
             
          2. **重要特許 (Top Picks)**: 
             - `<table>`タグを使用して整理。
             
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
          **重要**: 出力は純粋なHTMLコードのみを行ってください。Markdownのコードブロック（```html）は不要です。
          HTMLエンティティのエスケープ（&lt;など）はせず、そのままのタグ（<など）を出力してください。

          1. **全体総括**: 
             - トレンド分析。
             - `<div class="summary-box">` タグで特に重要な要約を囲ってください。
             
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
                system_instruction="Output raw HTML only. Do not escape HTML tags. No markdown fences."
            )
        )
        yield clean_html(response.text)

def clean_html(text):
    if not text: return ""
    text = str(text)
    
    # 1. HTMLアンエスケープ: モデルが &lt;h1&gt; のように返してきた場合、<h1> に戻す
    text = html.unescape(text)
    
    # 2. Markdownコードブロックの除去
    code_block_match = re.search(r"```(?:html)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()
    else:
        # コードブロックがない場合、"Here is the report:" などの前置き文章を除去する試み
        # 最初の < タグと、最後の > タグの間を抽出する
        start_tag = text.find("<")
        end_tag = text.rfind(">")
        if start_tag != -1 and end_tag != -1 and start_tag < end_tag:
            text = text[start_tag:end_tag+1]
        
        # 念のためバッククォート削除
        text = text.replace("```html", "").replace("```", "")
        
    return text.strip()

# --- Main Application ---

def main():
    if not check_password():
        st.stop()

    st.sidebar.title("🔬 PatentInsight AI")
    st.sidebar.caption("Speed & Bulk Edition")
    
    # --- API Key Loading Logic ---
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
                    # 途中経過はプログレスバーで表現し、テキストによるチラつきを防止
                    async for chunk in generate_final_report(clients, df, focus_keywords, exclude_keywords):
                        if len(chunk) < 200:
                            # 進捗メッセージのみ表示
                            result_container.caption(f"🔄 {chunk}")
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
                    # コピーボタンも少しリッチに
                    js_code = f"""
                    <script>
                    function copyReport() {{
                        const content = `{html_content.replace('`', '\`').replace('$', '\$')}`;
                        navigator.clipboard.writeText(content).then(function() {{
                            alert('レポートをコピーしました。');
                        }}, function(err) {{
                            console.error('Copy failed: ', err);
                        }});
                    }}
                    </script>
                    <div style="text-align: center; margin-top: 30px; margin-bottom: 50px;">
                        <button onclick="parent.document.execCommand('selectAll'); parent.document.execCommand('copy'); alert('レポートを選択しました。コピーしてください (Ctrl+C / Cmd+C)。');" 
                        style="background-color: #2563eb; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 16px; box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2); transition: all 0.2s;">
                        📋 全て選択してコピー (OneNote貼付用)
                        </button>
                    </div>
                    """
                    components.html(js_code, height=120)

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")

if __name__ == "__main__":
    main()
