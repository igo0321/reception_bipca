import streamlit as st
from pyairtable import Api

st.title("接続診断モード")

# 1. シークレットの読み込み確認
st.write("### 1. 設定ファイル(Secrets)の確認")
try:
    api_key = st.secrets["airtable"]["api_key"]
    base_id = st.secrets["airtable"]["base_id"]
    st.success(f"読み込み成功: APIキー(末尾={api_key[-4:]}), BaseID={base_id}")
except Exception as e:
    st.error(f"Secrets読み込み失敗: {e}")
    st.stop()

# 2. Airtableへの接続テスト
st.write("### 2. Airtable接続テスト")
try:
    api = Api(api_key)
    # Configテーブルの最初の1件だけ取得してみる
    table = api.table(base_id, 'Config')
    records = table.all(max_records=1)
    
    if records:
        st.success("✅ Airtableへの接続に成功しました！")
        st.json(records[0])
    else:
        st.warning("⚠️ 接続はできましたが、データが空です（Configテーブルにレコードがありません）。")
        
except Exception as e:
    st.error("❌ Airtable接続エラー発生")
    st.code(f"エラー内容: {e}")
    st.info("【考えられる原因】\n1. Base IDが間違っている（コピーミス）\n2. トークンに権限がない\n3. テーブル名 'Config' が存在しない（ベースの複製に失敗している）")
