import streamlit as st
import pandas as pd
from pyairtable import Api
from datetime import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

# --- 設定と定数 ---
st.set_page_config(page_title="コンクール当日受付システム", layout="wide")

# ▼対策②: ふわっとしたアニメーションを消してキビキビさせるCSS
st.markdown("""
<style>
    /* アプリ全体のアニメーションを無効化 */
    .stAppViewContainer {
        transition: none !important;
    }
    .element-container {
        transition: none !important;
    }
    /* ロディング中のインジケータを目立たなくする */
    .stSpinner {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# Airtable接続設定
try:
    api = Api(st.secrets["airtable"]["api_key"])
    base_id = st.secrets["airtable"]["base_id"]
    tbl_venues = api.table(base_id, 'Venues')
    tbl_submissions = api.table(base_id, 'Submissions')
    tbl_staff = api.table(base_id, 'Staff')
    tbl_config = api.table(base_id, 'Config')
    tbl_form_items = api.table(base_id, 'Form_Items')
    tbl_departments = api.table(base_id, 'Departments')
except Exception as e:
    st.error(f"Airtable接続設定エラー: secrets.tomlを確認してください。 {e}")
    st.stop()

# --- 関数定義（▼対策①: キャッシュの導入） ---

# ttl=600(秒)でキャッシュ有効期限を設定。
# 管理画面で更新した時はキャッシュをクリアする運用にします。

@st.cache_data(ttl=600, show_spinner=False)
def get_venues():
    """会場リスト取得（キャッシュ対応）"""
    return tbl_venues.all()

@st.cache_data(ttl=600, show_spinner=False)
def get_departments():
    """部門リスト取得（キャッシュ対応）"""
    depts = tbl_departments.all(formula="{Active}=1")
    depts.sort(key=lambda x: x['fields'].get('Order', 999))
    return depts

@st.cache_data(ttl=600, show_spinner=False)
def get_active_form_items():
    """質問項目取得（キャッシュ対応）"""
    items = tbl_form_items.all(formula="{Active}=1")
    items.sort(key=lambda x: x['fields'].get('Order', 999))
    return items

def clear_all_cache():
    """管理画面で更新があった時にキャッシュを捨てる関数"""
    st.cache_data.clear()

# --- その他の関数（キャッシュ不要） ---

def get_config_value(key):
    records = tbl_config.all(formula=f"{{Key}}='{key}'")
    if records:
        return records[0]['fields'].get('Value'), records[0]['id']
    return None, None

def update_config_value(key, new_value):
    current_val, record_id = get_config_value(key)
    if record_id:
        tbl_config.update(record_id, {"Value": new_value})
    else:
        tbl_config.create({"Key": key, "Value": new_value})

def send_notification_email(venue_name, participant_name, department, phone, details_text):
    try:
        smtp_server = st.secrets["mail"]["smtp_server"]
        smtp_port = st.secrets["mail"]["smtp_port"]
        sender_email = st.secrets["mail"]["sender_email"]
        sender_password = st.secrets["mail"]["sender_password"]
    except Exception:
        st.error("メールサーバー設定が見つかりません。")
        return False

    admin_email, _ = get_config_value('admin_email')
    if not admin_email:
        admin_email = sender_email 

    staff_records = tbl_staff.all(formula=f"{{Assigned_Venue}}='{venue_name}'")
    staff_emails = [s['fields'].get('Email') for s in staff_records if 'Email' in s['fields']]
    
    recipients = list(set([admin_email] + staff_emails))
    recipients = [r for r in recipients if r]

    if not recipients:
        return True

    subject = f"【受付通知】 {participant_name}（{venue_name}・{department}）"
    
    body = f"""
コンクール受付システムからの通知です。
以下の内容で受付が完了しました。

■ 会場: {venue_name}
■ 部門: {department}
■ 氏名: {participant_name}
■ 電話番号: {phone}

--------------------------------------------------
【詳細回答】
{details_text}
--------------------------------------------------
    """

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = formataddr(("コンクール受付システム", sender_email))
    msg['To'] = admin_email
    if staff_emails:
        msg['Cc'] = ", ".join(staff_emails)

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
    st.header("🏆 コンクール当日受付")
    
    if 'is_submitted' not in st.session_state:
        st.session_state.is_submitted = False
    if 'submitted_venue_msg' not in st.session_state:
        st.session_state.submitted_venue_msg = ""

    # --- 【完了画面】 ---
    if st.session_state.is_submitted:
        st.success("受付が完了しました")
        st.markdown("---")
        st.subheader("📣 出場者へのお知らせ")
        
        msg_display = st.session_state.submitted_venue_msg.replace('\n', '  \n')
        
        if msg_display:
            st.markdown(msg_display)
        else:
            st.info("係員の指示に従って待機してください。")
            
        st.markdown("---")
        st.caption("※この画面を閉じてしまっても受付は完了しています。")
        return

    # --- 【入力画面】 ---
    
    # キャッシュされた関数を使用
    venues_data = get_venues()
    active_venues = [
        v['fields'].get('Name') 
        for v in venues_data 
        if v['fields'].get('Active') and v['fields'].get('Name')
    ]
    
    if not active_venues:
        st.warning("現在受付中の会場はありません。")
        return

    # キャッシュされた関数を使用
    depts_data = get_departments()
    dept_names = [d['fields'].get('Name') for d in depts_data if d['fields'].get('Name')]
    if not dept_names:
        dept_names = ["部門設定なし"]

    st.write("以下のフォームに入力し、受付を行ってください。")

    selected_venue = st.selectbox("参加会場", active_venues)
    selected_dept = st.selectbox("出場部門", dept_names)

    # キャッシュされた関数を使用
    form_items = get_active_form_items()

    with st.form("reception_form"):
        name = st.text_input("出場者氏名", placeholder="例：山田 太郎")
        phone = st.text_input("緊急連絡先（電話番号）", placeholder="例：090-0000-0000")
            
        st.markdown("---")
        st.subheader("詳細事項")

        custom_responses = {}
        for item in form_items:
            f = item['fields']
            condition = f.get('Condition')
            
            if condition:
                cond_list = [c.strip() for c in condition.replace('、', ',').split(',')]
                if selected_dept not in cond_list:
                    continue 

            label = f.get('Label', '無題の質問')
            q_type = f.get('Type', 'text')
            options_str = f.get('Options', '')
            
            if q_type == 'text':
                custom_responses[label] = st.text_input(label)
            elif q_type == 'textarea':
                custom_responses[label] = st.text_area(label)
            elif q_type == 'select':
                opts = [opt.strip() for opt in options_str.split(',')] if options_str else []
                custom_responses[label] = st.selectbox(label, opts)
            elif q_type == 'checkbox':
                custom_responses[label] = st.checkbox(label)

        other_info = st.text_area("その他・連絡事項")
        
        submitted = st.form_submit_button("受付を完了する", use_container_width=True)

    if submitted:
        if not name or not phone:
            st.error("「氏名」と「電話番号」は必須です。")
        else:
            with st.spinner("送信中..."):
                details_str = ""
                for label, answer in custom_responses.items():
                    if isinstance(answer, bool):
                        answer = "はい" if answer else "いいえ"
                    details_str += f"【{label}】: {answer}\n"
                
                if other_info:
                    details_str += f"\n【その他】: {other_info}"

                tbl_submissions.create({
                    "Venue": selected_venue,
                    "Department": selected_dept,
                    "Name": name,
                    "Phone": phone,
                    "Other": details_str
                })
                
                send_notification_email(selected_venue, name, selected_dept, phone, details_str)
                
                target_venue = next(
                    (v for v in venues_data if v['fields'].get('Name') == selected_venue), 
                    None
                )
                msg_content = target_venue['fields'].get('Message', '') if target_venue else ''
                
                st.session_state.is_submitted = True
                st.session_state.submitted_venue_msg = msg_content
                st.rerun()

def page_staff_registration():
    st.header("スタッフメール通知登録")
    
    staff_pass_input = st.text_input("スタッフ用パスワードを入力してください", type="password")
    
    correct_staff_pass, _ = get_config_value('staff_password')
    if not correct_staff_pass:
        correct_staff_pass = "staff123"

    if staff_pass_input != correct_staff_pass:
        st.info("パスワードを入力すると登録フォームが表示されます。")
        st.stop() 

    st.divider()
    st.info("認証されました。登録フォームに入力してください。")
    
    venues_data = get_venues() # キャッシュ使用
    active_venues = [
        v['fields'].get('Name') 
        for v in venues_data 
        if v['fields'].get('Active') and v['fields'].get('Name')
    ]
    
    with st.form("staff_reg_form"):
        venue = st.selectbox("担当会場", active_venues)
        s_name = st.text_input("スタッフ氏名")
        s_email = st.text_input("通知先メールアドレス")
        reg_submit = st.form_submit_button("登録する")
        
    if reg_submit:
        if s_name and s_email:
            tbl_staff.create({"Name": s_name, "Email": s_email, "Assigned_Venue": venue})
            
            try:
                smtp_server = st.secrets["mail"]["smtp_server"]
                smtp_port = st.secrets["mail"]["smtp_port"]
                sender_email = st.secrets["mail"]["sender_email"]
                sender_password = st.secrets["mail"]["sender_password"]
                
                admin_email, _ = get_config_value('admin_email')
                if not admin_email:
                    admin_email = sender_email

                recipients = list(set([s_email, admin_email]))
                
                msg = MIMEText(f"{s_name}様\n\n{venue} の担当スタッフとして登録が完了しました。\n以後、この会場の受付通知が届きます。\n\n（※このメールは管理者にも通知されています）")
                msg['Subject'] = "【システム通知】スタッフ登録完了"
                msg['From'] = formataddr(("コンクール受付システム", sender_email))
                msg['To'] = s_email
                msg['Cc'] = admin_email
                
                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                        server.login(sender_email, sender_password)
                        server.send_message(msg, to_addrs=recipients)
                else:
                    with smtplib.SMTP(smtp_server, smtp_port) as server:
                        server.starttls()
                        server.login(sender_email, sender_password)
                        server.send_message(msg, to_addrs=recipients)

                st.success(f"{venue} の担当として {s_email} を登録し、確認メールを送信しました。")
            except Exception as e:
                 st.warning(f"登録は完了しましたが、メール送信に失敗しました: {e}")

        else:
            st.error("全ての項目を入力してください。")

def page_admin():
    st.header("⚙️ 管理画面")
    password_input = st.text_input("管理者パスワード", type="password")
    
    stored_pass, _ = get_config_value('admin_password')
    if not stored_pass:
        stored_pass = "admin" 
    
    if password_input != stored_pass:
        st.stop()
        
    st.success("認証成功")
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["会場管理", "部門管理", "入力項目設定", "スタッフ管理", "データ管理", "システム設定"])
    
    # --- Tab 1: 会場管理 ---
    with tab1:
        st.subheader("会場設定")
        st.caption("※お知らせメッセージは改行可能です。")
        with st.expander("➕ 新しい会場を追加"):
            with st.form("add_venue"):
                v_name = st.text_input("会場名")
                v_msg = st.text_area("完了時メッセージ")
                if st.form_submit_button("追加") and v_name:
                    tbl_venues.create({"Name": v_name, "Message": v_msg, "Active": True})
                    clear_all_cache() # キャッシュクリア
                    st.rerun()

        st.divider()
        venues = get_venues() # キャッシュ使用
        for v in venues:
            with st.expander(f"📍 {v['fields'].get('Name')}", expanded=False):
                with st.form(f"edit_venue_{v['id']}"):
                    new_name = st.text_input("会場名", value=v['fields'].get('Name'))
                    new_msg = st.text_area("完了時メッセージ（お知らせ）", value=v['fields'].get('Message', ''), height=150)
                    is_active = st.checkbox("受付中（有効）", value=v['fields'].get('Active', True))
                    
                    c1, c2 = st.columns([1, 1])
                    if c1.form_submit_button("更新保存"):
                        tbl_venues.update(v['id'], {
                            "Name": new_name, "Message": new_msg, "Active": is_active
                        })
                        clear_all_cache() # キャッシュクリア
                        st.success("更新しました")
                        time.sleep(1)
                        st.rerun()
                    if c2.form_submit_button("削除", type="primary"):
                        tbl_venues.delete(v['id'])
                        clear_all_cache() # キャッシュクリア
                        st.warning("削除しました")
                        time.sleep(1)
                        st.rerun()

    # --- Tab 2: 部門管理 ---
    with tab2:
        st.subheader("出場部門の設定")
        with st.expander("➕ 部門を追加"):
            with st.form("add_dept"):
                d_name = st.text_input("部門名（例：ピアノ部門）")
                d_order = st.number_input("表示順", value=1)
                if st.form_submit_button("追加") and d_name:
                    tbl_departments.create({"Name": d_name, "Order": d_order, "Active": True})
                    clear_all_cache() # キャッシュクリア
                    st.rerun()
        
        depts = get_departments() # キャッシュ使用
        for d in depts:
             with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 2])
                c1.write(f"順: {d['fields'].get('Order')}")
                c2.write(f"**{d['fields'].get('Name')}**")
                if c3.button("削除", key=f"del_dept_{d['id']}"):
                    tbl_departments.delete(d['id'])
                    clear_all_cache() # キャッシュクリア
                    st.rerun()

    # --- Tab 3: 入力項目設定 ---
    with tab3:
        st.subheader("受付フォームの追加質問項目")
        st.caption("条件欄に部門名を入力すると、その部門が選択された時のみ表示されます（カンマ区切りで複数可）。空欄なら全員に表示されます。")
        
        with st.expander("➕ 質問項目を追加する"):
            with st.form("add_item"):
                i_label = st.text_input("質問文（ラベル）")
                i_type = st.selectbox("入力タイプ", ["text", "textarea", "select", "checkbox"])
                i_options = st.text_input("選択肢（selectの場合カンマ区切り）")
                i_cond = st.text_input("表示条件（部門名）", placeholder="例：声楽部門, ミュージカル部門")
                i_order = st.number_input("表示順", value=1)
                
                if st.form_submit_button("追加"):
                    if i_label:
                        tbl_form_items.create({
                            "Label": i_label, "Type": i_type, "Options": i_options, 
                            "Condition": i_cond, "Order": i_order, "Active": True
                        })
                        clear_all_cache() # キャッシュクリア
                        st.success("追加しました")
                        time.sleep(1)
                        st.rerun()

        items = get_active_form_items() # キャッシュ使用
        for item in items:
            f = item['fields']
            with st.container(border=True):
                c1, c2, c3 = st.columns([0.5, 4, 1])
                c1.write(f"#{f.get('Order')}")
                cond_text = f"\n(条件: {f.get('Condition')})" if f.get('Condition') else ""
                c2.markdown(f"**{f.get('Label')}** ({f.get('Type')}){cond_text}")
                
                if c3.button("削除", key=f"del_item_{item['id']}"):
                    tbl_form_items.delete(item['id'])
                    clear_all_cache() # キャッシュクリア
                    st.rerun()

    # --- Tab 4: スタッフ管理 ---
    with tab4:
        st.subheader("スタッフ管理")
        staffs = tbl_staff.all()
        for s in staffs:
            c1, c2, c3 = st.columns([2, 3, 1])
            c1.write(s['fields'].get('Name'))
            c2.write(s['fields'].get('Email'))
            if c3.button("削除", key=s['id']):
                tbl_staff.delete(s['id'])
                st.rerun()

    # --- Tab 5: データ管理 ---
    with tab5:
        st.subheader("データ管理")
        subs = tbl_submissions.all()
        df = pd.DataFrame([s['fields'] for s in subs])
        st.write(f"受付件数: {len(df)}")
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 CSVダウンロード", csv, "data.csv", "text/csv")

    # --- Tab 6: システム設定 ---
    with tab6:
        st.subheader("管理者・システム設定")
        current_pass, _ = get_config_value('admin_password')
        current_staff_pass, _ = get_config_value('staff_password')
        current_email, _ = get_config_value('admin_email')
        
        with st.form("config_form"):
            new_pass = st.text_input("管理者パスワードの変更", value=current_pass if current_pass else "")
            new_staff_pass = st.text_input("スタッフ登録用パスワードの変更", value=current_staff_pass if current_staff_pass else "")
            new_email = st.text_input("管理者通知先メールアドレスの変更", value=current_email if current_email else "")
            
            if st.form_submit_button("設定を保存"):
                if new_pass: update_config_value('admin_password', new_pass)
                if new_staff_pass: update_config_value('staff_password', new_staff_pass)
                if new_email: update_config_value('admin_email', new_email)
                st.success("設定を保存しました。")
                time.sleep(1)
                st.rerun()

def main():
    st.sidebar.title("メニュー")
    page = st.sidebar.radio("移動先", ["出場者受付フォーム", "スタッフ登録", "管理者ログイン"])
    
    if page == "出場者受付フォーム":
        page_participant()
    elif page == "スタッフ登録":
        page_staff_registration()
    elif page == "管理者ログイン":
        page_admin()

if __name__ == "__main__":
    main()