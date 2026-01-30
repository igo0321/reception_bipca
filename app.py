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
    # 診断で成功したSecrets情報を使って接続します
    api = Api(st.secrets["airtable"]["api_key"])
    base_id = st.secrets["airtable"]["base_id"]
    
    # テーブル接続
    tbl_venues = api.table(base_id, 'Venues')       
    tbl_submissions = api.table(base_id, 'Submissions')
    tbl_staff = api.table(base_id, 'Staff')
    tbl_config = api.table(base_id, 'Config')
    tbl_form_items = api.table(base_id, 'Form_Items')
    tbl_departments = api.table(base_id, 'Departments') 
except Exception as e:
    st.error(f"Airtable接続エラー: {e}")
    st.stop()

# --- 関数定義（キャッシュ有効） ---

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_a_options():
    """セレクターA（会場）のリスト取得"""
    try:
        data = tbl_venues.all()
        data.sort(key=lambda x: x['fields'].get('Order', 999))
        return data
    except Exception:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def get_selector_b_options():
    """セレクターB（部門）のリスト取得"""
    try:
        data = tbl_departments.all(formula="{Active}=1")
        data.sort(key=lambda x: x['fields'].get('Order', 999))
        return data
    except Exception:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def get_active_form_items():
    """質問項目取得"""
    try:
        items = tbl_form_items.all(formula="{Active}=1")
        items.sort(key=lambda x: x['fields'].get('Order', 999))
        return items
    except Exception:
        return []

def clear_all_cache():
    st.cache_data.clear()

# --- ユーティリティ関数 ---

def delete_all_records(table_obj):
    """指定テーブルの全レコードを削除する（バッチ処理）"""
    try:
        all_records = table_obj.all()
        all_ids = [r['id'] for r in all_records]
        if all_ids:
            # 10件ずつバッチ削除（pyairtableが自動処理）
            table_obj.batch_delete(all_ids)
    except Exception as e:
        st.warning(f"削除処理中にエラーが発生しました（無視して続行します）: {e}")

# --- Config関連関数 ---

def get_config_value(key):
    try:
        records = tbl_config.all(formula=f"{{Key}}='{key}'")
        if records:
            return records[0]['fields'].get('Value'), records[0]['id']
    except Exception:
        pass
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
    try:
        all_configs = tbl_config.all()
        config_dict = {r['fields']['Key']: r['fields'].get('Value') for r in all_configs}
    except Exception:
        config_dict = {}
    
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
        return False

    admin_email = settings['admin_email']
    if not admin_email:
        admin_email = sender_email 

    staff_emails = []
    if val_a:
        try:
            staff_records = tbl_staff.all(formula=f"{{Assigned_Venue}}='{val_a}'")
            staff_emails = [s['fields'].get('Email') for s in staff_records if 'Email' in s['fields']]
        except:
            pass
    
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

    # 入力画面
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
            condition_str = f.get('Condition')
            show_item = True
            
            if condition_str:
                try:
                    cond_data = json.loads(condition_str)
                    target_venues = cond_data.get('venues', [])
                    target_depts = cond_data.get('depts', [])
                    if target_venues:
                        if not selected_val_a or selected_val_a not in target_venues:
                            show_item = False
                    if target_depts:
                        if not selected_val_b or selected_val_b not in target_depts:
                            show_item = False
                except json.JSONDecodeError:
                    if selected_val_b:
                        cond_list = [c.strip() for c in condition_str.replace('、', ',').split(',')]
                        if selected_val_b not in cond_list:
                            show_item = False
                    else:
                        show_item = False
            
            if not show_item:
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
                    if isinstance(answer, bool): answer = "はい" if answer else "いいえ"
                    details_str += f"【{label}】: {answer}\n"
                if other_info:
                    details_str += f"\n【その他】: {other_info}"

                try:
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
                except Exception as e:
                    st.error(f"送信エラーが発生しました: {e}")

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
            try:
                tbl_staff.create({"Name": s_name, "Email": s_email, "Assigned_Venue": venue})
                # メール送信処理（省略）
                st.success("登録しました。")
            except Exception as e:
                 st.warning(f"登録エラー: {e}")
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
    
    # Tab 1: セレクターA
    with tab1:
        st.subheader(f"{label_a} の管理")
        data_a = get_selector_a_options()
        current_orders = [x['fields'].get('Order', 0) for x in data_a]
        next_order = max(current_orders) + 1 if current_orders else 1
        
        with st.expander("➕ 新規追加", expanded=True):
            with st.form("add_a"):
                v_name = st.text_input("名称")
                v_msg = st.text_area("完了時メッセージ")
                v_order = st.number_input("表示順", value=next_order, step=1)
                
                if st.form_submit_button("追加") and v_name:
                    tbl_venues.create({"Name": v_name, "Message": v_msg, "Order": v_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        st.divider()
        for v in data_a:
            title = f"{v['fields'].get('Name')}"
            if not v['fields'].get('Active', True): title += " 【非公開】"
            with st.expander(title, expanded=False):
                with st.form(f"edit_a_form_{v['id']}"):
                    new_name = st.text_input("名称", value=v['fields'].get('Name'), key=f"name_{v['id']}")
                    new_msg = st.text_area("完了時メッセージ", value=v['fields'].get('Message', ''), height=100, key=f"msg_{v['id']}")
                    new_order = st.number_input("表示順", value=v['fields'].get('Order', 999), key=f"ord_{v['id']}")
                    is_active = st.checkbox("有効", value=v['fields'].get('Active', True), key=f"act_{v['id']}")
                    
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

    # Tab 2: セレクターB (バッチ処理)
    with tab2:
        st.subheader(f"{label_b} の管理")
        st.info("※テキストエリアで一括編集・並び替えができます。")
        current_data_b = get_selector_b_options()
        current_names_b = [d['fields'].get('Name') for d in current_data_b if d['fields'].get('Name')]
        default_text_b = "\n".join(current_names_b)
        
        with st.form("batch_edit_b"):
            updated_text_b = st.text_area("項目一覧（1行1項目）", value=default_text_b, height=300)
            if st.form_submit_button("保存して更新する"):
                new_names_b = [line.strip() for line in updated_text_b.split('\n') if line.strip()]
                with st.spinner("更新中..."):
                    old_ids_b = [d['id'] for d in current_data_b]
                    if old_ids_b:
                        tbl_departments.batch_delete(old_ids_b)
                        time.sleep(0.5)
                    
                    records_to_create = [{"Name": n, "Order": i+1, "Active": True} for i, n in enumerate(new_names_b)]
                    if records_to_create:
                        tbl_departments.batch_create(records_to_create)
                    
                    clear_all_cache()
                st.success(f"{len(new_names_b)}件の項目を更新しました。")
                time.sleep(1)
                st.rerun()

    # Tab 3: 入力項目
    with tab3:
        st.subheader("追加質問項目")
        opt_data_a = get_selector_a_options()
        opt_data_b = get_selector_b_options()
        opts_list_a = [o['fields'].get('Name') for o in opt_data_a if o['fields'].get('Name')]
        opts_list_b = [o['fields'].get('Name') for o in opt_data_b if o['fields'].get('Name')]

        with st.expander("➕ 新規追加"):
            with st.form("add_item"):
                i_label = st.text_input("質問ラベル")
                i_type = st.selectbox("タイプ", ["text", "textarea", "select", "checkbox"])
                i_options = st.text_input("選択肢(select用)")
                st.markdown("**表示条件設定**")
                cond_venues = st.multiselect(f"対象の{label_a}", opts_list_a)
                cond_depts = st.multiselect(f"対象の{label_b}", opts_list_b)
                i_order = st.number_input("順序", value=1)
                
                if st.form_submit_button("追加") and i_label:
                    cond_dict = {}
                    if cond_venues: cond_dict['venues'] = cond_venues
                    if cond_depts: cond_dict['depts'] = cond_depts
                    i_cond_str = json.dumps(cond_dict, ensure_ascii=False) if cond_dict else ""
                    
                    tbl_form_items.create({"Label": i_label, "Type": i_type, "Options": i_options, "Condition": i_cond_str, "Order": i_order, "Active": True})
                    clear_all_cache()
                    st.rerun()
        
        st.divider()
        items = get_active_form_items()
        item_types = ["text", "textarea", "select", "checkbox"]
        
        for item in items:
            f = item['fields']
            item_id = item['id']
            with st.expander(f"#{f.get('Order')} {f.get('Label')} [{f.get('Type')}]"):
                with st.form(key=f"edit_item_{item_id}"):
                    e_label = st.text_input("質問ラベル", value=f.get('Label'), key=f"el_{item_id}")
                    try: type_idx = item_types.index(f.get('Type', 'text'))
                    except: type_idx = 0
                    e_type = st.selectbox("タイプ", item_types, index=type_idx, key=f"et_{item_id}")
                    e_options = st.text_input("選択肢", value=f.get('Options', ''), key=f"eo_{item_id}")
                    e_order = st.number_input("順序", value=f.get('Order', 1), key=f"eord_{item_id}")
                    
                    st.write("**表示条件**")
                    raw_cond = f.get('Condition')
                    def_v, def_d = [], []
                    if raw_cond:
                        try:
                            cd = json.loads(raw_cond)
                            def_v, def_d = cd.get('venues', []), cd.get('depts', [])
                        except:
                            def_d = [x.strip() for x in raw_cond.split(',')]
                    
                    valid_v = [v for v in def_v if v in opts_list_a]
                    valid_d = [d for d in def_d if d in opts_list_b]
                    e_cv = st.multiselect(f"対象{label_a}", opts_list_a, default=valid_v, key=f"ecv_{item_id}")
                    e_cd = st.multiselect(f"対象{label_b}", opts_list_b, default=valid_d, key=f"ecd_{item_id}")
                    
                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("更新"):
                        nd = {}
                        if e_cv: nd['venues'] = e_cv
                        if e_cd: nd['depts'] = e_cd
                        ns = json.dumps(nd, ensure_ascii=False) if nd else ""
                        tbl_form_items.update(item_id, {"Label": e_label, "Type": e_type, "Options": e_options, "Condition": ns, "Order": e_order})
                        clear_all_cache()
                        st.success("更新しました")
                        time.sleep(1)
                        st.rerun()
                    if c2.form_submit_button("削除", type="primary"):
                        tbl_form_items.delete(item_id)
                        clear_all_cache()
                        st.rerun()

    # Tab 4: スタッフ
    with tab4:
        st.subheader("スタッフ管理")
        staffs = tbl_staff.all()
        for s in staffs:
            c1, c2, c3 = st.columns([2, 4, 1])
            c1.write(s['fields'].get('Assigned_Venue'))
            c2.write(f"{s['fields'].get('Name')} ({s['fields'].get('Email')})")
            if c3.button("削除", key=s['id']):
                tbl_staff.delete(s['id'])
                st.rerun()

    # Tab 5: データ
    with tab5:
        st.subheader("データ管理")
        subs = tbl_submissions.all()
        df = pd.DataFrame([s['fields'] for s in subs])
        st.write(f"件数: {len(df)}")
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("CSV DL", csv, "data.csv", "text/csv")

    # Tab 6: 設定・初期化
    with tab6:
        st.subheader("全体設定")
        with st.form("global_config"):
            c1, c2 = st.columns(2)
            n_la = c1.text_input("セレクター①名称", value=settings['label_a'])
            n_va = c2.checkbox("①を表示", value=settings['vis_a'])
            c3, c4 = st.columns(2)
            n_lb = c3.text_input("セレクター②名称", value=settings['label_b'])
            n_vb = c4.checkbox("②を表示", value=settings['vis_b'])
            n_ti = st.text_input("タイトル", value=settings['page_title'])
            
            if st.form_submit_button("設定保存"):
                update_config_value('label_selector_a', n_la)
                update_config_value('visible_selector_a', n_va)
                update_config_value('label_selector_b', n_lb)
                update_config_value('visible_selector_b', n_vb)
                update_config_value('page_title', n_ti)
                clear_all_cache()
                st.success("保存しました")
                time.sleep(1)
                st.rerun()

        st.divider()
        st.markdown("### ⚠️ システム初期化")
        with st.expander("初期化メニュー"):
            if st.checkbox("全データを削除して初期化する"):
                if st.button("初期化実行", type="primary"):
                    with st.spinner("初期化中（API制限回避のためゆっくり実行します）..."):
                        delete_all_records(tbl_submissions)
                        time.sleep(1)
                        delete_all_records(tbl_staff)
                        time.sleep(1)
                        delete_all_records(tbl_venues)
                        time.sleep(1)
                        delete_all_records(tbl_departments)
                        time.sleep(1)
                        delete_all_records(tbl_form_items)
                        time.sleep(1)
                        delete_all_records(tbl_config)
                        time.sleep(1)
                        
                        reset_pw = "iqqoo32i"
                        tbl_config.create({"Key": "admin_password", "Value": reset_pw})
                        tbl_config.create({"Key": "staff_password", "Value": reset_pw})
                        clear_all_cache()
                    st.success("初期化完了。パスワードは iqqoo32i です。")

def main():
    st.sidebar.title("メニュー")
    page = st.sidebar.radio("移動先", ["受付フォーム", "スタッフ登録", "管理者ログイン"])
    if page == "受付フォーム": page_participant()
    elif page == "スタッフ登録": page_staff_registration()
    elif page == "管理者ログイン": page_admin()

if __name__ == "__main__":
    main()
