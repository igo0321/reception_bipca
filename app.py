import streamlit as st
import pandas as pd
from pyairtable import Api
from datetime import datetime
import time
import smtplib
import json
from email.mime.text import MIMEText
from email.utils import formataddr

# --- 設定と定数 ---
st.set_page_config(page_title="受付システム", layout="wide")

# スタイル設定（UI調整）
st.markdown("""
<style>
    .stAppViewContainer { transition: none !important; }
    .element-container { transition: none !important; }
    .stSpinner { display: none; }
</style>
""", unsafe_allow_html=True)

# --- 共通関数：Airtable接続（遅延接続） ---
# 起動時に接続せず、呼ばれたときだけ接続します
def get_table(table_name):
    try:
        api_key = st.secrets["airtable"]["api_key"]
        base_id = st.secrets["airtable"]["base_id"]
        return Api(api_key).table(base_id, table_name)
    except Exception as e:
        st.error(f"Airtable接続設定エラー: {e}")
        st.stop()

# --- 設定読み込み（API消費ゼロ） ---
# Airtableではなく、secrets.tomlから読み込みます
def get_app_settings():
    try:
        cfg = st.secrets["app_settings"]
        return {
            'page_title': cfg.get('page_title', "受付システム"),
            'admin_email': cfg.get('admin_email', ""),
            'admin_password': cfg.get('admin_password', "admin"),
            'staff_password': cfg.get('staff_password', "staff123"),
            'label_a': cfg.get('label_selector_a', "参加会場"),
            'vis_a': cfg.get('visible_selector_a', True),
            'label_b': cfg.get('label_selector_b', "出場部門"),
            'vis_b': cfg.get('visible_selector_b', True),
        }
    except Exception:
        # 設定がない場合のデフォルト
        return {
            'page_title': "受付システム",
            'admin_email': "",
            'admin_password': "admin",
            'staff_password': "staff",
            'label_a': "参加会場", 'vis_a': True,
            'label_b': "出場部門", 'vis_b': True
        }

# --- データ取得関数（キャッシュ有効） ---

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_a_options():
    try:
        # ここで初めて通信が発生
        return get_table('Venues').all(sort=["Order"])
    except Exception:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_b_options():
    try:
        return get_table('Departments').all(formula="{Active}=1", sort=["Order"])
    except Exception:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def get_active_form_items():
    try:
        return get_table('Form_Items').all(formula="{Active}=1", sort=["Order"])
    except Exception:
        return []

def clear_all_cache():
    st.cache_data.clear()

# --- ユーティリティ ---

def delete_all_records(table_name):
    """指定テーブルの全レコードを削除（バッチ処理）"""
    try:
        tbl = get_table(table_name)
        all_records = tbl.all()
        all_ids = [r['id'] for r in all_records]
        if all_ids:
            tbl.batch_delete(all_ids)
    except Exception as e:
        st.warning(f"削除エラー: {e}")

# --- メール送信関数 ---

def send_notification_email(settings, val_a, val_b, name, phone, details_text):
    try:
        smtp_server = st.secrets["mail"]["smtp_server"]
        smtp_port = st.secrets["mail"]["smtp_port"]
        sender_email = st.secrets["mail"]["sender_email"]
        sender_password = st.secrets["mail"]["sender_password"]
    except Exception:
        return False

    admin_email = settings['admin_email']
    if not admin_email: admin_email = sender_email 

    staff_emails = []
    if val_a:
        try:
            # 必要な時だけ接続
            staff_records = get_table('Staff').all(formula=f"{{Assigned_Venue}}='{val_a}'")
            staff_emails = [s['fields'].get('Email') for s in staff_records if 'Email' in s['fields']]
        except:
            pass
    
    recipients = list(set([admin_email] + staff_emails))
    recipients = [r for r in recipients if r]
    if not recipients: return True

    subject_parts = [name]
    if val_a: subject_parts.append(val_a)
    if val_b: subject_parts.append(val_b)
    
    subject = f"【受付通知】 {' / '.join(subject_parts)}"
    
    body = f"""
受付システムからの通知です。

■ {settings['label_a']}: {val_a if val_a else '(未設定)'}
■ {settings['label_b']}: {val_b if val_b else '(未設定)'}
■ 氏名: {name}
■ 電話番号: {phone}

--------------------------------------------------
【詳細回答】
{details_text}
--------------------------------------------------
    """
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = formataddr((settings['page_title'], sender_email))
    msg['To'] = admin_email
    if staff_emails: msg['Cc'] = ", ".join(staff_emails)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_password)
                server.send_message(msg, to_addrs=recipients)
        return True
    except Exception as e:
        st.error(f"メール送信エラー: {e}")
        return False

# --- ページ定義 ---

def page_participant():
    settings = get_app_settings()
    st.header(settings['page_title'])

    # 【重要】開始ボタンによる防御壁
    # Botや再起動ループが来ても、このボタンを押さない限りAPIは1回も消費されません
    if 'reception_started' not in st.session_state:
        st.session_state.reception_started = False
    
    if not st.session_state.reception_started:
        st.info("以下のボタンを押して受付を開始してください。")
        if st.button("受付を開始する", type="primary"):
            st.session_state.reception_started = True
            st.rerun()
        return

    # --- ここから下は人間がボタンを押した後にしか実行されません ---

    if 'is_submitted' not in st.session_state:
        st.session_state.is_submitted = False
    if 'submitted_msg' not in st.session_state:
        st.session_state.submitted_msg = ""

    if st.session_state.is_submitted:
        st.success("受付が完了しました")
        st.markdown("---")
        msg_display = st.session_state.submitted_msg.replace('\n', '  \n')
        if msg_display: st.markdown(msg_display)
        else: st.info("受付が完了いたしました。")
        st.markdown("---")
        if st.button("トップに戻る"):
            st.session_state.is_submitted = False
            st.session_state.reception_started = False # 最初に戻る
            st.rerun()
        return

    # 入力画面
    selected_val_a = None
    active_opts_a = []
    
    if settings['vis_a']:
        # キャッシュが効くので2回目以降はAPI消費ゼロ
        data_a = get_selector_a_options()
        active_opts_a = [v['fields'].get('Name') for v in data_a if v['fields'].get('Active') and v['fields'].get('Name')]
        if not active_opts_a:
            st.warning(f"現在受付可能な{settings['label_a']}はありません。")
            return
        selected_val_a = st.selectbox(settings['label_a'], active_opts_a)
    
    selected_val_b = None
    if settings['vis_b']:
        data_b = get_selector_b_options()
        opts_b = [d['fields'].get('Name') for d in data_b if d['fields'].get('Name')]
        if not opts_b: opts_b = ["設定なし"]
        selected_val_b = st.selectbox(settings['label_b'], opts_b)

    form_items = get_active_form_items()
    st.write("以下のフォームに入力し、受付を行ってください。")

    with st.form("reception_form"):
        name = st.text_input("氏名", placeholder="例：山田 太郎")
        phone = st.text_input("緊急連絡先（電話番号）", placeholder="例：090-0000-0000")
        st.markdown("---")
        
        custom_responses = {}
        for item in form_items:
            f = item['fields']
            # 条件判定ロジック（省略せずに実装）
            show_item = True
            cond_str = f.get('Condition')
            if cond_str:
                try:
                    cd = json.loads(cond_str)
                    tv, td = cd.get('venues', []), cd.get('depts', [])
                    if tv and (not selected_val_a or selected_val_a not in tv): show_item = False
                    if td and (not selected_val_b or selected_val_b not in td): show_item = False
                except:
                    pass # 旧形式などは無視
            
            if not show_item: continue

            label = f.get('Label', '質問')
            q_type = f.get('Type', 'text')
            options_str = f.get('Options', '')
            
            if q_type == 'text': custom_responses[label] = st.text_input(label)
            elif q_type == 'textarea': custom_responses[label] = st.text_area(label)
            elif q_type == 'select':
                opts = [o.strip() for o in options_str.split(',')] if options_str else []
                custom_responses[label] = st.selectbox(label, opts)
            elif q_type == 'checkbox': custom_responses[label] = st.checkbox(label)

        other_info = st.text_area("その他・連絡事項")
        submitted = st.form_submit_button("受付を完了する", use_container_width=True)

    if submitted:
        if not name or not phone:
            st.error("「氏名」と「電話番号」は必須です。")
        else:
            with st.spinner("送信中..."):
                details_str = ""
                for label, answer in custom_responses.items():
                    if isinstance(answer, bool): answer = "はい" if answer else "いいえ"
                    details_str += f"【{label}】: {answer}\n"
                if other_info: details_str += f"\n【その他】: {other_info}"

                try:
                    # 送信時のみ接続
                    tbl_sub = get_table('Submissions')
                    tbl_sub.create({
                        "Venue": selected_val_a if selected_val_a else "(非表示)",
                        "Department": selected_val_b if selected_val_b else "(非表示)",
                        "Name": name, "Phone": phone, "Other": details_str
                    })
                    
                    send_notification_email(settings, selected_val_a, selected_val_b, name, phone, details_str)
                    
                    # 完了メッセージ取得
                    msg_content = ""
                    if selected_val_a:
                        all_venues = get_selector_a_options()
                        target = next((v for v in all_venues if v['fields'].get('Name') == selected_val_a), None)
                        if target: msg_content = target['fields'].get('Message', '')
                    
                    st.session_state.is_submitted = True
                    st.session_state.submitted_msg = msg_content
                    st.rerun()
                except Exception as e:
                    st.error(f"送信エラー: {e}")

def page_staff_registration():
    settings = get_app_settings()
    st.header(f"スタッフ登録")
    
    staff_pass_input = st.text_input("スタッフ用パスワード", type="password")
    if staff_pass_input != settings['staff_password']:
        st.stop() 

    st.divider()
    data_a = get_selector_a_options()
    active_opts_a = [v['fields'].get('Name') for v in data_a if v['fields'].get('Active')]
    
    with st.form("staff_reg"):
        venue = st.selectbox(f"担当する{settings['label_a']}", active_opts_a)
        s_name = st.text_input("スタッフ氏名")
        s_email = st.text_input("通知先メールアドレス")
        if st.form_submit_button("登録"):
            if s_name and s_email:
                try:
                    get_table('Staff').create({"Name": s_name, "Email": s_email, "Assigned_Venue": venue})
                    st.success("登録しました")
                except Exception as e:
                    st.error(f"エラー: {e}")

def page_admin():
    st.header("⚙️ 管理画面")
    password_input = st.text_input("管理者パスワード", type="password")
    
    settings = get_app_settings()
    if password_input != settings['admin_password']:
        st.stop()
        
    st.success("認証成功")
    label_a = settings['label_a']
    label_b = settings['label_b']

    # ※「全体設定」タブは削除しました（Secretsで管理するため）
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        f"{label_a}設定", f"{label_b}設定", "入力項目", "スタッフ", "データ"
    ])
    
    # Tab 1: セレクターA
    with tab1:
        st.subheader(f"{label_a}")
        tbl_venues = get_table('Venues')
        data_a = get_selector_a_options()
        current_orders = [x['fields'].get('Order', 0) for x in data_a]
        next_order = max(current_orders) + 1 if current_orders else 1
        
        with st.expander("➕ 新規追加"):
            with st.form("add_a"):
                v_name = st.text_input("名称")
                v_msg = st.text_area("完了時メッセージ")
                v_order = st.number_input("表示順", value=next_order)
                if st.form_submit_button("追加") and v_name:
                    tbl_venues.create({"Name": v_name, "Message": v_msg, "Order": v_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        
        for v in data_a:
            with st.expander(f"{v['fields'].get('Name')}"):
                with st.form(f"ea_{v['id']}"):
                    nn = st.text_input("名称", v['fields'].get('Name'))
                    nm = st.text_area("Msg", v['fields'].get('Message', ''))
                    no = st.number_input("順", value=v['fields'].get('Order', 0))
                    na = st.checkbox("有効", v['fields'].get('Active', True))
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("更新"):
                        tbl_venues.update(v['id'], {"Name": nn, "Message": nm, "Order": no, "Active": na})
                        clear_all_cache()
                        st.rerun()
                    if c2.form_submit_button("削除", type="primary"):
                        tbl_venues.delete(v['id'])
                        clear_all_cache()
                        st.rerun()

    # Tab 2: セレクターB (バッチ)
    with tab2:
        st.subheader(f"{label_b}")
        tbl_depts = get_table('Departments')
        data_b = get_selector_b_options()
        names_b = [d['fields'].get('Name') for d in data_b if d['fields'].get('Name')]
        
        with st.form("batch_b"):
            txt_b = st.text_area("項目一覧（1行1項目）", value="\n".join(names_b), height=300)
            if st.form_submit_button("全更新"):
                new_names = [x.strip() for x in txt_b.split('\n') if x.strip()]
                old_ids = [d['id'] for d in data_b]
                if old_ids: tbl_depts.batch_delete(old_ids)
                time.sleep(0.5)
                if new_names:
                    recs = [{"Name": n, "Order": i+1, "Active": True} for i, n in enumerate(new_names)]
                    tbl_depts.batch_create(recs)
                clear_all_cache()
                st.success("更新完了")
                time.sleep(1)
                st.rerun()

    # Tab 3: 入力項目
    with tab3:
        st.subheader("質問項目")
        tbl_items = get_table('Form_Items')
        items = get_active_form_items()
        
        with st.expander("➕ 追加"):
            with st.form("add_i"):
                il = st.text_input("ラベル")
                it = st.selectbox("タイプ", ["text", "textarea", "select", "checkbox"])
                io = st.text_input("選択肢")
                io_ord = st.number_input("順序", value=1)
                if st.form_submit_button("追加") and il:
                    tbl_items.create({"Label": il, "Type": it, "Options": io, "Order": io_ord, "Active": True})
                    clear_all_cache()
                    st.rerun()
        
        for item in items:
            with st.expander(f"{item['fields'].get('Label')}"):
                if st.button("削除", key=f"del_{item['id']}"):
                    tbl_items.delete(item['id'])
                    clear_all_cache()
                    st.rerun()

    # Tab 4: スタッフ
    with tab4:
        st.subheader("スタッフ一覧")
        staffs = get_table('Staff').all()
        for s in staffs:
            c1, c2 = st.columns([4, 1])
            c1.write(f"{s['fields'].get('Name')} ({s['fields'].get('Assigned_Venue')})")
            if c2.button("削除", key=s['id']):
                get_table('Staff').delete(s['id'])
                st.rerun()

    # Tab 5: データDL & 初期化
    with tab5:
        st.subheader("データDL")
        subs = get_table('Submissions').all()
        if subs:
            df = pd.DataFrame([s['fields'] for s in subs])
            st.download_button("CSV DL", df.to_csv(index=False).encode('utf-8-sig'), "data.csv")
        
        st.divider()
        if st.checkbox("データ初期化（全削除）"):
            if st.button("実行", type="primary"):
                with st.spinner("初期化中..."):
                    delete_all_records('Submissions')
                    time.sleep(1)
                    delete_all_records('Staff')
                    time.sleep(1)
                    delete_all_records('Venues')
                    time.sleep(1)
                    delete_all_records('Departments')
                    time.sleep(1)
                    delete_all_records('Form_Items')
                    # ConfigはAirtableにないので削除不要
                    clear_all_cache()
                st.success("完了")

def main():
    st.sidebar.title("メニュー")
    page = st.sidebar.radio("移動先", ["受付フォーム", "スタッフ登録", "管理者ログイン"])
    if page == "受付フォーム": page_participant()
    elif page == "スタッフ登録": page_staff_registration()
    elif page == "管理者ログイン": page_admin()

if __name__ == "__main__":
    main()
