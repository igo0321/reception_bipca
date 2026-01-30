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
        
        # --- 自動連番の計算 ---
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
        
        # --- 編集リスト ---
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

    # Tab 2: セレクターB設定 (★ここをバッチ処理に修正★)
    with tab2:
        st.subheader(f"{label_b} の管理 (データのみ)")
        st.info("※テキストエリアで一括編集・並び替えができます。上から順に表示されます。")
        
        current_data_b = get_selector_b_options()
        current_names_b = [d['fields'].get('Name') for d in current_data_b if d['fields'].get('Name')]
        default_text_b = "\n".join(current_names_b)
        
        with st.form("batch_edit_b"):
            updated_text_b = st.text_area(
                "項目一覧（1行1項目）",
                value=default_text_b,
                height=300,
                help="項目を追加、削除、並び替えする場合はここで編集して保存してください。"
            )
            
            if st.form_submit_button("保存して更新する"):
                new_names_b = [line.strip() for line in updated_text_b.split('\n') if line.strip()]
                with st.spinner("更新中..."):
                    # 1. 既存データを全削除
                    old_ids_b = [d['id'] for d in current_data_b]
                    if old_ids_b:
                        tbl_departments.batch_delete(old_ids_b)
                        time.sleep(0.2) # 少し待機
                    
                    # 2. 新しいデータを辞書リストとして作成
                    records_to_create = []
                    for i, name in enumerate(new_names_b):
                        records_to_create.append({
                            "Name": name, 
                            "Order": i + 1, 
                            "Active": True
                        })
                    
                    # 3. バッチ作成 (APIリクエスト回数を大幅削減)
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
                i_options = st.text_input("選択肢(select用, カンマ区切り)")
                
                st.markdown("---")
                st.markdown("**表示条件設定**（何も選択しない場合は「全員」に表示）")
                
                cond_venues = st.multiselect(f"対象の{label_a}", opts_list_a)
                cond_depts = st.multiselect(f"対象の{label_b}", opts_list_b)
                
                i_order = st.number_input("順序", value=1)
                
                if st.form_submit_button("追加") and i_label:
                    cond_dict = {}
                    if cond_venues: cond_dict['venues'] = cond_venues
                    if cond_depts: cond_dict['depts'] = cond_depts
                    
                    i_cond_str = json.dumps(cond_dict, ensure_ascii=False) if cond_dict else ""
                    
                    tbl_form_items.create({
                        "Label": i_label, 
                        "Type": i_type, 
                        "Options": i_options, 
                        "Condition": i_cond_str, 
                        "Order": i_order, 
                        "Active": True
                    })
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
                    
                    curr_type = f.get('Type', 'text')
                    try:
                        type_idx = item_types.index(curr_type)
                    except ValueError:
                        type_idx = 0
                    e_type = st.selectbox("タイプ", item_types, index=type_idx, key=f"et_{item_id}")
                    
                    e_options = st.text_input("選択肢(select用)", value=f.get('Options', ''), key=f"eo_{item_id}")
                    e_order = st.number_input("順序", value=f.get('Order', 1), key=f"eord_{item_id}")
                    
                    st.markdown("---")
                    st.write("**表示条件の編集**")
                    
                    raw_cond = f.get('Condition')
                    default_v = []
                    default_d = []
                    if raw_cond:
                        try:
                            c_data = json.loads(raw_cond)
                            default_v = c_data.get('venues', [])
                            default_d = c_data.get('depts', [])
                        except:
                            default_d = [x.strip() for x in raw_cond.split(',')]
                    
                    valid_def_v = [v for v in default_v if v in opts_list_a]
                    valid_def_d = [d for d in default_d if d in opts_list_b]

                    e_cond_v = st.multiselect(f"対象の{label_a}", opts_list_a, default=valid_def_v, key=f"ecv_{item_id}")
                    e_cond_d = st.multiselect(f"対象の{label_b}", opts_list_b, default=valid_def_d, key=f"ecd_{item_id}")
                    
                    col_update, col_delete = st.columns([1, 1])
                    
                    if col_update.form_submit_button("更新"):
                        new_cond_dict = {}
                        if e_cond_v: new_cond_dict['venues'] = e_cond_v
                        if e_cond_d: new_cond_dict['depts'] = e_cond_d
                        
                        new_cond_str = json.dumps(new_cond_dict, ensure_ascii=False) if new_cond_dict else ""
                        
                        tbl_form_items.update(item_id, {
                            "Label": e_label,
                            "Type": e_type,
                            "Options": e_options,
                            "Condition": new_cond_str,
                            "Order": e_order
                        })
                        clear_all_cache()
                        st.success("更新しました")
                        time.sleep(1)
                        st.rerun()

                    if col_delete.form_submit_button("削除", type="primary"):
                        tbl_form_items.delete(item_id)
                        clear_all_cache()
                        st.rerun()

    # Tab 4: スタッフ管理
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
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("CSV DL (Excel対応版)", csv, "data.csv", "text/csv")

    # Tab 6: 全体設定 & リセット (★ここにSleepを追加★)
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

       # --- システム初期化セクション ---
        st.divider()
        st.markdown("### ⚠️ システム初期化・リセット")
        st.warning("【注意】この操作を行うと、受付データだけでなく、**設定した「セレクターの中身」「質問項目」「画面の名称設定」など、すべてのデータ**が完全に削除され、初期状態に戻ります。")
        
        with st.expander("初期化メニューを開く"):
            confirm_reset = st.checkbox("すべてのデータを削除し、初期化することを承認します")
            if confirm_reset:
                if st.button("完全初期化を実行する", type="primary"):
                    with st.spinner("全データを削除・初期化中..."):
                        # 少しSleepを入れてAPI制限回避
                        delete_all_records(tbl_submissions)
                        time.sleep(0.5)
                        delete_all_records(tbl_staff)
                        time.sleep(0.5)
                        
                        delete_all_records(tbl_venues)
                        time.sleep(0.5)
                        delete_all_records(tbl_departments)
                        time.sleep(0.5)
                        delete_all_records(tbl_form_items)
                        time.sleep(0.5)
                        
                        delete_all_records(tbl_config)
                        time.sleep(0.5)
                        
                        reset_pw = "iqqoo32i"
                        tbl_config.create({"Key": "admin_password", "Value": reset_pw})
                        tbl_config.create({"Key": "staff_password", "Value": reset_pw})
                        
                        clear_all_cache()
                        
                    st.success("システムを完全に初期化しました。")
                    st.info(f"管理者・スタッフ用パスワードは **{reset_pw}** に設定されました。")
