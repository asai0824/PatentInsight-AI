import streamlit as st
import pandas as pd
import os
import time
import asyncio
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

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # パスワードをセッションから削除
        else:
            st.session_state["password_correct"] = False

    # 初回アクセス時または認証未完了時
    if "password_correct" not in st.session_state:
        # パスワード入力フォームを表示
        st.title("🔒 ログイン")
        st.write("このアプリを使用するにはパスワードが必要です。")
        st.text_input(
            "パスワード", type="password", on_change=password_entered, key="password"
        )
        return False
    
    # パスワードが間違っていた場合
    elif not st.session_state["password_correct"]:
        st.title("🔒 ログイン")
        st.text_input(
            "パスワード", type="password", on_change=password_entered, key="password"
        )
        st.error("パスワードが間違っています。")
        return False
    
    # 認証成功時
    else:
        return True

# --- CSS Injection for Report Styling (OneNote Compatibility) ---
# React版のCSSを移植
REPORT_CSS = """
<style>
    .report-content {
        background-color: white;
        color: #0f172a;
        font-family: "Noto Sans JP", "Meiryo", sans-serif;
        line-height: 1.8;
        padding: 2rem;
        border: 1px solid #e2e8f0;
        border-radius: 0.75rem;
    }
    .report-content h1 { 
        font-size: 24px; font-weight: bold; color: #1e3a8a; 
        border-bottom: 2px solid #1e3a8a; padding-bottom: 10px; 
        margin-bottom: 20px; margin-top: 30px; 
    }
    .report-content h2 { 
        font-size: 20px; font-weight: bold; color: #1e40af; 
        background-color: #eff6ff; padding: 8px 12px; 
        border-left: 5px solid #1e40af; margin-bottom: 16px; margin-top: 24px; 
    }
    .report-content h3 { 
        font-size: 18px; font-weight: bold; color: #0f172a; 
        border-bottom: 1px solid #cbd5e1; padding-bottom: 4px; 
        margin-bottom: 12px; margin-top: 20px; 
    }
    .report-content p { margin-bottom: 1em; text-align: justify; }
    .report-content ul { list-style-type: disc; padding-left: 24px; margin-bottom: 16px; }
    .report-content li { margin-bottom: 8px; }
    .report-content strong { color: #1d4ed8; font-weight: bold; }
    .report-content table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 0.9em; }
    .report-content th { background-color: #f1f5f9; border: 1px solid #cbd5e1; padding: 8px; text-align: left; font-weight: bold; color: #334155; }
    .report-content td { border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }
</style>
"""

# --- Logic: Data Compression & Helper Functions ---

def truncate_text(text, max_length):
    if pd.isna(text) or text == "":
        return ""
    s = str(text)
    if len(s) <= max_length:
        return s
    return s[:max_length] + "..."

def compress_patent_row(row):
    """
    1行の特許データを圧縮文字列に変換する。
    重要なカラム（発明、要約、請求項など）を優先して含め、トークン数を節約する。
    """
    priority_keys = ['title', 'invention', 'abstract', 'claim', 'applicant', 'number', 'publication', 'id', '発明', '名称', '要約', '請求', '出願人', '番号']
    
    # Seriesを辞書に変換
    row_dict = row.to_dict()
    
    # 優先キーに基づいてソートするためのスコア付け
    sorted_items = []
    for k, v in row_dict.items():
        if pd.isna(v) or v == "":
            continue
        
        k_str = str(k).lower()
        is_priority = any(pk in k_str for pk in priority_keys)
        score = 0 if is_priority else 1
        sorted_items.append((score, k, v))
    
    # ソート（優先キーが先）
    sorted_items.sort(key=lambda x: x[0])
    
    row_string = ""
    for _, k, v in sorted_items:
        # 厳格な切り詰め: キー30文字、値300文字
        k_trunc = truncate_text(k, 30)
        v_trunc = truncate_text(v, 300)
        
        row_string += f"{k_trunc}: {v_trunc} | "
        
        # 1行あたりのハードリミット (トークン節約の要)
        if len(row_string) > 1500:
            row_string += "[TRUNCATED]"
            break
            
    return row_string

# --- Logic: Gemini API Interaction ---

async def analyze_batch(client, rows_text, focus_keywords, exclude_keywords, batch_index, total_batches):
    """
    データのバッチ（塊）を分析して中間レポートを作成する
    """
    prompt = f"""
    あなたは特許分析の専門家です。
    大規模な特許調査の一部（Batch {batch_index + 1}/{total_batches}）を担当しています。
    
    以下の特許データを分析し、**中間分析レポート**を作成してください。
    このレポートは後で他のバッチの結果と統合されるため、具体的な事実と重要な特許の抽出に焦点を当ててください。

    ### ユーザーの着目点
    {focus_keywords or "特になし（全体的なトレンド）"}

    ### 除外条件（この条件に合うものは無視してください）
    {exclude_keywords or "特になし"}

    ### 出力すべき内容 (プレーンテキストで箇条書き)
    1. **主な技術クラスター**: このバッチ内で見られた主な技術トピック（例：正極材、製造装置など）。
    2. **重要特許候補**: 着目点に合致する、または新規性が高いと思われる特許（公報番号、出願人、理由）。
    3. **出願人トレンド**: このバッチ内で目立つ出願人。
    
    ※ 除外・ノイズに関する報告は不要です。重要な情報のみを抽出してください。

    ### データ
    {rows_text}
    """

    try:
        response = await client.aio.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Analyze the patent batch objectively."
            )
        )
        return response.text or ""
    except Exception as e:
        return f"Error in batch {batch_index}: {str(e)}"

async def generate_final_report(client, data_frames, focus_keywords, exclude_keywords):
    """
    メインの生成ロジック。
    データ量に応じてシングルパスかMap-Reduceかを選択する。
    """
    total_rows = len(data_frames)
    
    # 各行を圧縮文字列に変換
    compressed_rows = [compress_patent_row(row) for _, row in data_frames.iterrows()]
    
    CHUNK_SIZE = 400
    
    if total_rows <= CHUNK_SIZE:
        # --- Single Pass Strategy ---
        status_text = f"全{total_rows}件を一括分析中..."
        yield status_text
        
        data_string = "\n---\n".join(compressed_rows)
        
        prompt = f"""
          あなたは熟練した特許弁理士であり、かつ材料科学のトップエキスパートです。
          提供された特許リストを元に、研究開発者が短時間で技術動向を把握できる「特許調査レポート」を作成してください。

          ### 目的
          ノイズを除去し、重要な技術トレンド、競合の動き、および注目すべき特許を抽出すること。
          A4用紙 2〜10枚程度（日本語4,000〜15,000文字程度）の分量にまとめてください。

          ### ユーザー指定の条件
          - **着目キーワード**: {focus_keywords or "全体的な技術トレンド"}
          - **除外対象**: {exclude_keywords or "特になし"}
          ※ 除外対象やノイズと思われる特許については、レポートに含めないでください。

          ### レポート構成（HTML形式のみ出力）
          <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>, <table> タグを使用。
          
          1. **全体総括コメント**: 
             - Excelシート全体を通した所感を記述してください。
             - どのような特許が多かったか？
             - 最近の出願傾向や技術トレンドは？
             - 特徴的な特許を重点的に出している出願人の動きなど。
          
          2. **重要特許ピックアップ (Top Picks)**: 
             - 特に重要と思われる特許を5〜10件厳選。
             - **必ずHTMLの <table> タグを使用**して、公報番号、出願人、発明名称、技術的特徴を整理して表示してください。Markdownの表は使用禁止です。

          3. **技術カテゴリ別詳解**: 
             - トピックごとのグルーピング解説。
             - 「どの企業がどんな課題解決に取り組んでいるか」を記述。

          ### データ
          {data_string}
        """

        response = await client.aio.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="You are a professional patent analyst. Output raw HTML. Do not use Markdown for tables."
            )
        )
        
        yield clean_html(response.text)
        
    else:
        # --- Map-Reduce Strategy ---
        chunks = []
        for i in range(0, total_rows, CHUNK_SIZE):
            chunks.append(compressed_rows[i : i + CHUNK_SIZE])
        
        total_chunks = len(chunks)
        batch_summaries = []
        
        for i, chunk in enumerate(chunks):
            yield f"大規模データ分析中: パート {i+1}/{total_chunks} を処理しています..."
            chunk_text = "\n---\n".join(chunk)
            summary = await analyze_batch(client, chunk_text, focus_keywords, exclude_keywords, i, total_chunks)
            batch_summaries.append(summary)
            # APIレート制限への簡易的な配慮
            await asyncio.sleep(1)

        combined_summaries = "\n\n".join([f"--- Batch {i+1} Report ---\n{s}" for i, s in enumerate(batch_summaries)])
        
        yield "最終レポートを統合・執筆中..."
        
        final_prompt = f"""
          あなたは特許分析の専門家です。
          大規模な特許データセットを複数のバッチに分けて分析しました。
          以下は、各バッチからの「中間分析レポート」の集合です。

          これらを統合し、最終的な「特許調査レポート」を作成してください。
          情報の重複を整理し、全体としての傾向を導き出してください。

          ### ユーザー指定の条件
          - **着目キーワード**: {focus_keywords or "全体的な技術トレンド"}
          - **除外対象**: {exclude_keywords or "特になし"}

          ### レポート構成（HTML形式のみ出力）
          <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>, <table> タグを使用。
          
          1. **全体総括コメント**: 
             - 全バッチを統合した上での、データ全体を通した所感。
             - どのような特許が多かったか、最近の出願傾向、注目の出願人など。
          
          2. **重要特許ピックアップ (Top Picks)**: 
             - 中間レポートで挙げられた候補から特に重要なものを5〜10件厳選。
             - **必ずHTMLの <table> タグを使用**して、公報番号、出願人、発明名称、技術的特徴を整理して表示してください。Markdownの表は使用禁止です。

          3. **技術カテゴリ別詳解**: 
             - トピックごとのグルーピング解説。

          ※ ノイズや除外された特許に関するコメントは不要です。

          ### 中間レポート集合
          {combined_summaries}
        """

        response = await client.aio.models.generate_content(
            model='gemini-3-flash-preview',
            contents=final_prompt,
            config=types.GenerateContentConfig(
                system_instruction="You are a professional patent analyst. Output raw HTML. Do not use Markdown for tables."
            )
        )
        
        yield clean_html(response.text)

def clean_html(text):
    if not text: return ""
    return text.replace("```html", "").replace("```", "")

# --- Main Application ---

def main():
    # パスワード認証チェック（ここより下は認証通過後のみ実行される）
    if not check_password():
        st.stop()

    # Sidebar
    st.sidebar.title("🔬 PatentInsight AI")
    st.sidebar.caption("Bulk Report Edition")
    
    # ユーザー用APIキー入力（認証されたユーザーが入れる）
    # もしくはSecretsにAPI_KEYも設定してあれば自動で読み込む
    default_api_key = os.environ.get("API_KEY") or st.secrets.get("API_KEY", "")
    
    api_key = st.sidebar.text_input("Gemini API Key", value=default_api_key, type="password")
    
    if not api_key:
        st.sidebar.warning("API Keyを入力してください。")
        st.stop()
        
    client = Client(api_key=api_key)

    st.sidebar.markdown("---")
    
    uploaded_file = st.sidebar.file_uploader("Excelファイルをアップロード", type=['xlsx', 'xls', 'xlsm'])
    
    focus_keywords = st.sidebar.text_area(
        "着目テーマ・キーワード",
        placeholder="例：全固体電池の硫化物系電解質における界面抵抗低減技術...",
        height=100
    )
    
    exclude_keywords = st.sidebar.text_area(
        "除外・スキップ条件",
        placeholder="例：半導体製造装置そのもの、リチウムイオン電池以外...",
        height=80
    )

    # Main Area
    st.title("特許調査レポート生成")
    st.markdown("""
    Excelデータをアップロードすると、AIが内容を読み込み、技術動向や重要特許をまとめたレポートを作成します。
    結果はOneNote等にそのまま貼り付け可能な形式で出力されます。
    """)

    if uploaded_file:
        try:
            df = pd.read_excel(uploaded_file)
            st.success(f"ファイル読み込み完了: {len(df)}件のデータ")
            
            if st.button("分析開始 (Start Analysis)", type="primary"):
                result_container = st.empty()
                progress_bar = st.progress(0)
                
                # 非同期ジェネレータを同期的に回すためのラッパー
                async def run_analysis():
                    final_html = ""
                    step = 0
                    async for chunk in generate_final_report(client, df, focus_keywords, exclude_keywords):
                        step += 1
                        # チャンクが短い場合はステータスメッセージとみなす
                        if len(chunk) < 200:
                            result_container.info(chunk)
                            # 進捗バーを適当に進める
                            current_progress = min(step * 10, 90)
                            progress_bar.progress(current_progress)
                        else:
                            final_html = chunk
                    return final_html

                html_content = asyncio.run(run_analysis())
                
                progress_bar.progress(100)
                result_container.empty() # ステータス消去
                
                if html_content:
                    st.markdown("### 生成レポート")
                    
                    # HTMLの表示 (unsafe_allow_html=TrueでDOMに直接注入し、コピペしやすくする)
                    full_html = f"{REPORT_CSS}<div class='report-content'>{html_content}</div>"
                    st.markdown(full_html, unsafe_allow_html=True)
                    
                    # コピー用ボタン（JavaScriptハック）
                    # Streamlitはサーバーサイドのため、クライアントのクリップボード操作にはJSが必要
                    import streamlit.components.v1 as components
                    js_code = f"""
                    <script>
                    function copyReport() {{
                        const content = `{html_content.replace('`', '\`').replace('$', '\$')}`;
                        // テキストとしてのコピーではなく、HTMLとしてのコピーが理想だが、
                        // 簡易的にクリップボードAPIを使用
                        navigator.clipboard.writeText(content).then(function() {{
                            alert('HTMLソースをコピーしました。OneNoteには「形式を選択して貼り付け」などを利用するか、ブラウザ上の表示を範囲選択してコピーしてください。');
                        }}, function(err) {{
                            console.error('Async: Could not copy text: ', err);
                        }});
                    }}
                    </script>
                    <div style="text-align: right; margin-top: 10px;">
                        <button onclick="parent.document.execCommand('selectAll'); parent.document.execCommand('copy'); alert('レポート全体を選択・コピーしました。OneNoteに貼り付けてください。');" 
                        style="background-color: #2563eb; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold;">
                        📋 レポートを選択してコピー
                        </button>
                        <p style="font-size: 12px; color: #64748b; margin-top: 5px;">
                        ※ボタンを押すと全選択＆コピーを試みます。<br>うまくいかない場合は手動で範囲選択してコピーしてください。
                        </p>
                    </div>
                    """
                    components.html(js_code, height=100)

        except Exception as e:
            st.error(f"エラーが発生しました: {str(e)}")
            st.warning("Excelファイルの形式を確認してください（1行目がヘッダーである必要があります）。")

if __name__ == "__main__":
    main()
