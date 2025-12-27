import streamlit as st
import pandas as pd
from pyairtable import Api
from datetime import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

# --- 設定と定数 ---
st.set_page_config(page_title="受付システム", layout="wide")

# スタイル設定（高速化・UI調整）
st.markdown("""
<style>
    .stAppViewContainer { transition: none !important; }
    .element-container { transition: none !important; }
    .stSpinner { display: none; }
</style>
""", unsafe_allow_html=True)

# Airtable接続設定
try:
    api = Api(st.secrets["airtable"]["api_key"])
    base_id = st.secrets["airtable"]["base_id"]
    tbl_venues = api.table(base_id, 'Venues')       # セレクターA（通知紐づけ用）
    tbl_submissions = api.table(base_id, 'Submissions')
    tbl_staff = api.table(base_id, 'Staff')
    tbl_config = api.table(base_id, 'Config')
    tbl_form_items = api.table(base_id, 'Form_Items')
    tbl_departments = api.table(base_id, 'Departments') # セレクターB（データ用）
except Exception as e:
    st.error(f"Airtable接続設定エラー: secrets.tomlを確認してください。 {e}")
    st.stop()

# --- 関数定義（キャッシュ有効） ---

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_a_options():
    """セレクターA（旧会場）のリスト取得"""
    data = tbl_venues.all()
    data.sort(key=lambda x: x['fields'].get('Order', 999))
    return data

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_b_options():
    """セレクターB（旧部門）のリスト取得"""
    data = tbl_departments.all(formula="{Active}=1")
    data.sort(key=lambda x: x['fields'].get('Order', 999))
    return data

@st.cache_data(ttl=600, show_spinner=False)
def get_active_form_items():
    """質問項目取得"""
    items = tbl_form_items.all(formula="{Active}=1")
    items.sort(key=lambda x: x['fields'].get('Order', 999))
    return items

def clear_all_cache():
    st.cache_data.clear()

# --- Config関連関数 ---

def get_config_value(key):
    records = tbl_config.all(formula=f"{{Key}}='{key}'")
    if records:
        return records[0]['fields'].get('Value'), records[0]['id']
    return None, None

def update_config_value(key, new_value):
    if isinstance(new_value, bool):
        new_value = "True" if new_value else "False"
        
    current_val, record_id = get_config_value(key)
    if record_id:
        tbl_config.update(record_id, {"Value": str(new_value)})
    else:
        tbl_config.create({"Key": key, "Value": str(new_value)})

def get_app_settings():
    """アプリ全体の表示設定を一括取得"""
    settings = {}
    
    # Config全件取得
    all_configs = tbl_config.all()
    config_dict = {r['fields']['Key']: r['fields'].get('Value') for r in all_configs}
    
    settings['page_title'] = config_dict.get('page_title', "受付システム")
    settings['admin_email'] = config_dict.get('admin_email', "")
    
    settings['label_a'] = config_dict.get('label_selector_a', "参加会場")
    settings['vis_a'] = config_dict.get('visible_selector_a', "True") == "True"
    
    settings['label_b'] = config_dict.get('label_selector_b', "出場部門")
    settings['vis_b'] = config_dict.get('visible_selector_b', "True") == "True"
    
    return settings

# --- メール送信関数 ---

def send_notification_email(settings, val_a, val_b, name, phone, details_text):
    try:
        smtp_server = st.secrets["mail"]["smtp_server"]
        smtp_port = st.secrets["mail"]["smtp_port"]
        sender_email = st.secrets["mail"]["sender_email"]
        sender_password = st.secrets["mail"]["sender_password"]
    except Exception:
        st.error("メールサーバー設定が見つかりません。")
        return False

    admin_email = settings['admin_email']
    if not admin_email:
        admin_email = sender_email 

    # スタッフアドレス取得
    staff_emails = []
    if val_a:
        staff_records = tbl_staff.all(formula=f"{{Assigned_Venue}}='{val_a}'")
        staff_emails = [s['fields'].get('Email') for s in staff_records if 'Email' in s['fields']]
    
    # 送信先リスト作成（管理者 + スタッフ）
    recipients = list(set([admin_email] + staff_emails))
    recipients = [r for r in recipients if r]

    if not recipients:
        return True

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
    settings = get_app_settings()
    st.header(settings['page_title'])
    
    if 'is_submitted' not in st.session_state:
        st.session_state.is_submitted = False
    if 'submitted_msg' not in st.session_state:
        st.session_state.submitted_msg = ""

    # --- 【完了画面】 ---
    if st.session_state.is_submitted:
        st.success("受付が完了しました")
        st.markdown("---")
        st.subheader("📣 お知らせ")
        
        msg_display = st.session_state.submitted_msg.replace('\n', '  \n')
        
        if msg_display:
            st.markdown(msg_display)
        else:
            st.info("受付が完了いたしました。")
            
        st.markdown("---")
        st.caption("※この画面を閉じてしまっても受付は完了しています。")
        return

    # --- 【入力画面】 ---
    
    selected_val_a = None
    active_opts_a = []
    
    if settings['vis_a']:
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
        st.subheader("詳細事項")

        custom_responses = {}
        for item in form_items:
            f = item['fields']
            condition = f.get('Condition')
            
            if condition:
                if not selected_val_b: continue
                cond_list = [c.strip() for c in condition.replace('、', ',').split(',')]
                if selected_val_b not in cond_list: continue 

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
                    "Venue": selected_val_a if selected_val_a else "(非表示)",
                    "Department": selected_val_b if selected_val_b else "(非表示)",
                    "Name": name,
                    "Phone": phone,
                    "Other": details_str
                })
                
                send_notification_email(settings, selected_val_a, selected_val_b, name, phone, details_str)
                
                msg_content = ""
                if selected_val_a:
                    all_venues = get_selector_a_options()
                    target = next((v for v in all_venues if v['fields'].get('Name') == selected_val_a), None)
                    if target:
                        msg_content = target['fields'].get('Message', '')
                
                st.session_state.is_submitted = True
                st.session_state.submitted_msg = msg_content
                st.rerun()

def page_staff_registration():
    settings = get_app_settings()
    st.header(f"スタッフ登録 ({settings['label_a']}担当)")
    
    staff_pass_input = st.text_input("スタッフ用パスワード", type="password")
    correct_staff_pass, _ = get_config_value('staff_password')
    if not correct_staff_pass: correct_staff_pass = "staff123"

    if staff_pass_input != correct_staff_pass:
        st.stop() 

    st.divider()
    
    data_a = get_selector_a_options()
    active_opts_a = [v['fields'].get('Name') for v in data_a if v['fields'].get('Active') and v['fields'].get('Name')]
    
    if not active_opts_a:
        st.warning(f"現在登録可能な{settings['label_a']}はありません。")
        return

    with st.form("staff_reg_form"):
        venue = st.selectbox(f"担当する{settings['label_a']}", active_opts_a)
        s_name = st.text_input("スタッフ氏名")
        s_email = st.text_input("通知先メールアドレス")
        reg_submit = st.form_submit_button("登録する")
        
    if reg_submit:
        if s_name and s_email:
            tbl_staff.create({"Name": s_name, "Email": s_email, "Assigned_Venue": venue})
            
            # スタッフ登録通知（管理者へもCC）
            try:
                smtp_server = st.secrets["mail"]["smtp_server"]
                smtp_port = st.secrets["mail"]["smtp_port"]
                sender_email = st.secrets["mail"]["sender_email"]
                sender_password = st.secrets["mail"]["sender_password"]
                
                # 設定から管理者メアド取得
                admin_email = settings['admin_email']
                if not admin_email: admin_email = sender_email

                # 送信先: 本人 + 管理者
                recipients = list(set([s_email, admin_email]))
                
                msg = MIMEText(f"{s_name}様\n\n{venue} ({settings['label_a']}) の担当として登録しました。\n\n（※本メールは管理者 {admin_email} にも通知されています）")
                msg['Subject'] = "【システム通知】スタッフ登録完了"
                msg['From'] = formataddr((settings['page_title'], sender_email))
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
                st.success("登録完了メールを送信しました。")
            except Exception as e:
                 st.warning(f"登録しましたがメール送信に失敗: {e}")
        else:
            st.error("入力不備があります。")

def page_admin():
    st.header("⚙️ 管理画面")
    password_input = st.text_input("管理者パスワード", type="password")
    
    stored_pass, _ = get_config_value('admin_password')
    if not stored_pass: stored_pass = "admin" 
    
    if password_input != stored_pass:
        st.stop()
        
    st.success("認証成功")
    
    settings = get_app_settings()
    label_a = settings['label_a']
    label_b = settings['label_b']

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        f"{label_a}設定", 
        f"{label_b}設定", 
        "入力項目", "スタッフ", "データ", "全体設定"
    ])
    
    # Tab 1: セレクターA設定
    with tab1:
        st.subheader(f"{label_a} の管理 (通知連携あり)")
        with st.expander("➕ 新規追加"):
            with st.form("add_a"):
                v_name = st.text_input("名称")
                v_msg = st.text_area("完了時メッセージ")
                v_order = st.number_input("表示順", value=1)
                if st.form_submit_button("追加") and v_name:
                    tbl_venues.create({"Name": v_name, "Message": v_msg, "Order": v_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        st.divider()
        data_a = get_selector_a_options()
        for v in data_a:
            title = f"{v['fields'].get('Name')}"
            if not v['fields'].get('Active', True): title += " 【非公開】"
            with st.expander(title, expanded=False):
                with st.form(f"edit_a_{v['id']}"):
                    new_name = st.text_input("名称", value=v['fields'].get('Name'))
                    new_msg = st.text_area("完了時メッセージ", value=v['fields'].get('Message', ''), height=100)
                    new_order = st.number_input("表示順", value=v['fields'].get('Order', 999))
                    is_active = st.checkbox("有効", value=v['fields'].get('Active', True))
                    
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("更新"):
                        tbl_venues.update(v['id'], {"Name": new_name, "Message": new_msg, "Order": new_order, "Active": is_active})
                        clear_all_cache()
                        st.success("更新しました")
                        time.sleep(1)
                        st.rerun()
                    if c2.form_submit_button("削除", type="primary"):
                        tbl_venues.delete(v['id'])
                        clear_all_cache()
                        st.rerun()

    # Tab 2: セレクターB設定
    with tab2:
        st.subheader(f"{label_b} の管理 (データのみ)")
        with st.expander("➕ 新規追加"):
            with st.form("add_b"):
                d_name = st.text_input("名称")
                d_order = st.number_input("表示順", value=1)
                if st.form_submit_button("追加") and d_name:
                    tbl_departments.create({"Name": d_name, "Order": d_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        
        data_b = get_selector_b_options()
        for d in data_b:
             with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                c1.write(f"順:{d['fields'].get('Order')}")
                c2.write(f"**{d['fields'].get('Name')}**")
                if c3.button("削除", key=f"del_b_{d['id']}"):
                    tbl_departments.delete(d['id'])
                    clear_all_cache()
                    st.rerun()

    # Tab 3: 入力項目
    with tab3:
        st.subheader("追加質問項目")
        with st.expander("➕ 追加"):
            with st.form("add_item"):
                i_label = st.text_input("質問ラベル")
                i_type = st.selectbox("タイプ", ["text", "textarea", "select", "checkbox"])
                i_options = st.text_input("選択肢(select用)")
                i_cond = st.text_input(f"表示条件({label_b}名)")
                i_order = st.number_input("順序", value=1)
                if st.form_submit_button("追加") and i_label:
                    tbl_form_items.create({"Label": i_label, "Type": i_type, "Options": i_options, "Condition": i_cond, "Order": i_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        
        items = get_active_form_items()
        for item in items:
            f = item['fields']
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 4, 1])
                c1.write(f"#{f.get('Order')}")
                cond = f" (条件: {f.get('Condition')})" if f.get('Condition') else ""
                c2.write(f"**{f.get('Label')}** [{f.get('Type')}]{cond}")
                if c3.button("削除", key=item['id']):
                    tbl_form_items.delete(item['id'])
                    clear_all_cache()
                    st.rerun()

    # Tab 4: スタッフ管理 (機能改善箇所)
    with tab4:
        st.subheader("スタッフ管理")
        st.caption(f"各スタッフの紐づき状況: {label_a}")
        
        staffs = tbl_staff.all()
        
        h1, h2, h3, h4 = st.columns([2, 2, 3, 1])
        h1.markdown(f"**担当{label_a}**")
        h2.markdown("**氏名**")
        h3.markdown("**メール**")
        
        for s in staffs:
            c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
            assigned_venue = s['fields'].get('Assigned_Venue', '(未設定)')
            
            c1.write(assigned_venue)
            c2.write(s['fields'].get('Name'))
            c3.write(s['fields'].get('Email'))
            
            if c4.button("削除", key=s['id']):
                tbl_staff.delete(s['id'])
                st.rerun()

    # Tab 5: データ管理
    with tab5:
        st.subheader("データ管理")
        subs = tbl_submissions.all()
        df = pd.DataFrame([s['fields'] for s in subs])
        st.write(f"件数: {len(df)}")
        if not df.empty:
            # BOM付きUTF-8で文字化け防止
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("CSV DL (Excel対応版)", csv, "data.csv", "text/csv")

    # Tab 6: 全体設定
    with tab6:
        st.subheader("全体設定・名称変更")
        with st.form("global_config"):
            st.markdown("##### 🏷️ 表示名と表示ON/OFF")
            col_a1, col_a2 = st.columns([3, 1])
            new_label_a = col_a1.text_input("セレクター①の名称（メール紐づけあり）", value=settings['label_a'])
            new_vis_a = col_a2.checkbox("①を表示する", value=settings['vis_a'])
            
            col_b1, col_b2 = st.columns([3, 1])
            new_label_b = col_b1.text_input("セレクター②の名称（データのみ）", value=settings['label_b'])
            new_vis_b = col_b2.checkbox("②を表示する", value=settings['vis_b'])

            st.divider()
            st.markdown("##### 🔐 認証・その他")
            new_title = st.text_input("画面タイトル", value=settings['page_title'])
            new_pass = st.text_input("管理者パスワード", value="*****") 
            new_staff_pass = st.text_input("スタッフ登録パスワード")
            new_email = st.text_input("管理者メール")

            if st.form_submit_button("全設定を保存"):
                update_config_value('label_selector_a', new_label_a)
                update_config_value('visible_selector_a', new_vis_a)
                update_config_value('label_selector_b', new_label_b)
                update_config_value('visible_selector_b', new_vis_b)
                update_config_value('page_title', new_title)
                
                if new_pass != "*****" and new_pass: update_config_value('admin_password', new_pass)
                if new_staff_pass: update_config_value('staff_password', new_staff_pass)
                if new_email: update_config_value('admin_email', new_email)

                clear_all_cache()
                st.success("設定を更新しました。")
                time.sleep(1)
                st.rerun()

def main():
    st.sidebar.title("メニュー")
    page = st.sidebar.radio("移動先", ["受付フォーム", "スタッフ登録", "管理者ログイン"])
    
    if page == "受付フォーム":
        page_participant()
    elif page == "スタッフ登録":
        page_staff_registration()
    elif page == "管理者ログイン":
        page_admin()

if __name__ == "__main__":
    main()
