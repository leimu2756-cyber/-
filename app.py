import os
import bcrypt
import pandas as pd
import streamlit as st

from cleaner import SmartCleaner
from db import get_engine, get_session, init_db, fetch_one, fetch_all, execute
from sqlalchemy import text

# ============================================================
# 0. 設定
# ============================================================
MASTER_PASSWORD = '2012011220120629LryCsy'
ADMIN_EMAIL = '717804lin@gmail.com'

init_db()

st.set_page_config(
    page_title="AI 資料清理工作台",
    page_icon="🧹",
    layout="wide",
)

for key, default in [('logged_in', False), ('user_role', None), ('username', None)]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================
# 1. 側邊欄
# ============================================================
st.sidebar.title("🧹 AI 資料清理工作台")
client_page = None

if not st.session_state['logged_in']:
    nav = st.sidebar.radio("選擇身分", ["客戶登入", "客戶註冊", "管理員後台"])

    if nav == "客戶登入":
        u = st.sidebar.text_input("帳號")
        p = st.sidebar.text_input("密碼", type="password")
        if st.sidebar.button("登入"):
            if not u or not p:
                st.sidebar.warning("請輸入帳號與密碼")
            else:
                row = fetch_one(
                    "SELECT password FROM users WHERE username = :u", {"u": u}
                )
                if row and bcrypt.checkpw(p.encode('utf-8'), row[0].encode('utf-8')):
                    st.session_state.update(
                        logged_in=True, user_role='client', username=u
                    )
                    st.rerun()
                else:
                    st.sidebar.error("帳號或密碼錯誤")

    elif nav == "客戶註冊":
        u = st.sidebar.text_input("設定帳號")
        p = st.sidebar.text_input("設定密碼", type="password")
        contact = st.sidebar.text_input("聯絡方式 (Line / Email / 電話)")
        if st.sidebar.button("註冊"):
            if not (u and p and contact):
                st.sidebar.warning("請填寫所有欄位")
            else:
                existing = fetch_one(
                    "SELECT username FROM users WHERE username = :u", {"u": u}
                )
                if existing:
                    st.sidebar.error("此帳號已被註冊")
                else:
                    hashed = bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt())
                    execute(
                        "INSERT INTO users (username, password, contact) "
                        "VALUES (:u, :p, :c)",
                        {"u": u, "p": hashed.decode('utf-8'), "c": contact},
                    )
                    st.sidebar.success("註冊成功！請登入並回報匯款資訊。")

    elif nav == "管理員後台":
        mp = st.sidebar.text_input("管理員密碼", type="password")
        if st.sidebar.button("進入後台"):
            if mp == MASTER_PASSWORD:
                st.session_state.update(
                    logged_in=True, user_role='admin', username='MasterAdmin'
                )
                st.rerun()
            else:
                st.sidebar.error("密碼錯誤")

else:
    st.sidebar.success(f"已登入：{st.session_state['username']}")
    st.sidebar.caption(
        f"角色：{'管理員' if st.session_state['user_role'] == 'admin' else '客戶'}"
    )
    if st.session_state['user_role'] == 'client':
        client_page = st.sidebar.radio(
            "功能選單", ["🧹 資料清理工作台", "💬 意見反饋"]
        )
    if st.sidebar.button("登出"):
        st.session_state.update(logged_in=False, user_role=None, username=None)
        st.rerun()


# ============================================================
# 2. 未登入首頁
# ============================================================
if not st.session_state['logged_in']:
    st.title("🧹 AI 資料清理工作台")
    st.info("👈 請從左側選單登入、註冊，或以管理員密碼進入後台。")
    col1, col2, col3 = st.columns(3)
    col1.metric("已服務客戶", "0", "即將上線")
    col2.metric("平均清理時間", "< 30 秒", "比手動快 200 倍")
    col3.metric("資料外洩事件", "0", "檔案自動銷毀")
    st.markdown(f"""
### 💡 核心功能
1. **AI 欄位識別** — 自動判斷 Email、手機、身分證、日期、金額等格式
2. **資料品質報告** — 缺失值、重複率、格式一致性完整分析
3. **一鍵清理管線** — 去重、補空白、電話 / 日期 / Email 標準化
4. **異常值偵測** — IQR 法找出數值離群值、格式混用警告
5. **隱私保護** — 資料僅在記憶體處理，密碼 bcrypt 雜湊儲存

### 📮 需要客製化服務？
直接來信：[{ADMIN_EMAIL}](mailto:{ADMIN_EMAIL})
""")


# ============================================================
# 3. 管理員後台
# ============================================================
elif st.session_state['user_role'] == 'admin':
    st.title("🛠️ 管理員控制後台")
    tab1, tab2, tab3 = st.tabs(["👥 客戶管理", "📊 使用紀錄", "💬 客戶反饋"])

    with tab1:
        rows = fetch_all(
            "SELECT username, contact, amount, last5, status, plan, usage_count, created_at FROM users"
        )
        if not rows:
            st.info("目前尚無客戶註冊。")
        else:
            st.subheader(f"📋 客戶列表（共 {len(rows)} 位）")
            for row in rows:
                with st.container():
                    cols = st.columns([2, 2, 1.5, 1.5, 1.5, 1.5])
                    cols[0].write(f"**帳號**：{row[0]}")
                    cols[1].write(f"**聯絡**：{row[1]}")
                    cols[2].write(f"**金額**：{row[2] or '—'}")
                    cols[3].write(f"**末五碼**：{row[3] or '—'}")
                    cols[4].write(f"**使用次數**：{row[6]}")
                    status = row[4]
                    if status == '已開通':
                        cols[5].success(status)
                    elif status == '已封鎖':
                        cols[5].error(status)
                    else:
                        cols[5].warning(status)
                    btns = st.columns([1, 1, 1, 4])
                    if btns[0].button("🟢 開通", key=f"unlock_{row[0]}"):
                        execute("UPDATE users SET status='已開通' WHERE username=:u", {"u": row[0]})
                        st.rerun()
                    if btns[1].button("🔴 封鎖", key=f"block_{row[0]}"):
                        execute("UPDATE users SET status='已封鎖' WHERE username=:u", {"u": row[0]})
                        st.rerun()
                    if btns[2].button("🔄 重設", key=f"reset_{row[0]}"):
                        execute("UPDATE users SET status='未審核' WHERE username=:u", {"u": row[0]})
                        st.rerun()
                    st.divider()

    with tab2:
        rows = fetch_all(
            "SELECT username, filename, rows, cols, actions, timestamp FROM usage_log ORDER BY id DESC LIMIT 100"
        )
        if not rows:
            st.info("目前尚無使用紀錄。")
        else:
            df_logs = pd.DataFrame(rows, columns=["使用者", "檔案", "列數", "欄數", "操作", "時間"])
            st.dataframe(df_logs, use_container_width=True)

    with tab3:
        rows = fetch_all(
            "SELECT id, username, subject, message, contact, status, timestamp FROM feedback ORDER BY id DESC"
        )
        if not rows:
            st.info("目前尚無客戶反饋。")
        else:
            st.subheader(f"📬 共 {len(rows)} 筆反饋")
            filter_status = st.selectbox("篩選狀態", ["全部", "未處理", "已處理"])
            for row in rows:
                if filter_status != "全部" and row[5] != filter_status:
                    continue
                with st.container():
                    head_cols = st.columns([4, 2, 2])
                    head_cols[0].markdown(f"### {row[2] or '（無主旨）'}")
                    head_cols[1].caption(f"來自：{row[1]}")
                    head_cols[2].caption(f"{row[6]}")
                    st.markdown(f"**聯絡方式**：{row[4] or '（未提供）'}")
                    st.info(row[3])
                    if row[5] == '已處理':
                        st.success("✅ 已處理")
                    else:
                        st.warning("⏳ 未處理")
                    btn = st.columns([1, 1, 5])
                    if row[5] != '已處理':
                        if btn[0].button("✅ 標記已處理", key=f"fb_done_{row[0]}"):
                            execute("UPDATE feedback SET status='已處理' WHERE id=:i", {"i": row[0]})
                            st.rerun()
                    else:
                        if btn[0].button("↩️ 改回未處理", key=f"fb_undo_{row[0]}"):
                            execute("UPDATE feedback SET status='未處理' WHERE id=:i", {"i": row[0]})
                            st.rerun()
                    if btn[1].button("🗑️ 刪除", key=f"fb_del_{row[0]}"):
                        execute("DELETE FROM feedback WHERE id=:i", {"i": row[0]})
                        st.rerun()
                    st.divider()


# ============================================================
# 4. 客戶端
# ============================================================
elif st.session_state['user_role'] == 'client':
    current_user = st.session_state['username']
    user_row = fetch_one(
        "SELECT amount, last5, status FROM users WHERE username = :u",
        {"u": current_user},
    )
    db_amount, db_last5, db_status = user_row

    if client_page == "💬 意見反饋":
        st.title("💬 意見反饋與客製化需求")
        st.markdown(f"""
有任何問題、想許願新功能、或需要 **客製化資料處理服務**？
兩種方式任選：

**方式一**：直接寄信到我的信箱 👉 [{ADMIN_EMAIL}](mailto:{ADMIN_EMAIL}?subject=資料清理需求)

**方式二**：填寫下方表單，我會在後台看到，並用你留的聯絡方式回覆你。
""")
        st.divider()
        default_contact = fetch_one(
            "SELECT contact FROM users WHERE username = :u", {"u": current_user}
        )
        default_contact = default_contact[0] if default_contact else ''
        with st.form("feedback_form", clear_on_submit=True):
            subject = st.text_input("主旨", placeholder="例如：需要合併 50 個分店的月報表")
            contact = st.text_input("你的聯絡方式（方便我回覆你）", value=default_contact)
            message = st.text_area(
                "需求描述", height=200,
                placeholder="請盡量描述：\n1. 你的資料長什麼樣子\n2. 你想達成什麼目標\n3. 目前怎麼手動處理、大概花多久\n4. 期望什麼時候完成",
            )
            submitted = st.form_submit_button("📨 送出需求", type="primary")
            if submitted:
                if not message.strip():
                    st.warning("請至少填寫需求描述。")
                else:
                    execute(
                        "INSERT INTO feedback (username, subject, message, contact) "
                        "VALUES (:u, :s, :m, :c)",
                        {"u": current_user, "s": subject or '（無主旨）', "m": message, "c": contact},
                    )
                    st.success("✅ 已送出！我會盡快用你留的聯絡方式回覆你。")
                    st.balloons()
        st.divider()
        st.caption("💡 已送出過的反饋，可從管理員後台查看處理狀態。")

    else:
        st.title(f"👋 歡迎回來，{current_user}")
        if db_status != '已開通':
            st.warning(
                f"🔒 **目前帳號狀態：【{db_status}】** —— 請完成付款並回報，"
                "管理員確認後將立即開通工具權限。"
            )
            st.subheader("💳 匯款資訊")
            st.markdown("""
            * **金融機構**：台灣銀行（代號 `004`）
            * **匯款帳號**：`請爸爸提供後填入`
            * **匯款金額**：依您選擇的方案（單次 NT$299 / 月付 NT$399 / 年付 NT$3,990）
            """)
            with st.form("payment_form"):
                amt = st.text_input("匯款金額", value=db_amount or '')
                last5 = st.text_input("轉帳帳號末五碼", value=db_last5 or '', max_chars=5)
                if st.form_submit_button("送出匯款回報"):
                    if amt and last5:
                        execute(
                            "UPDATE users SET amount=:a, last5=:l, status='未審核' WHERE username=:u",
                            {"a": amt, "l": last5, "u": current_user},
                        )
                        st.success("匯款資訊已送出，請等候管理員對帳開通。")
                        st.rerun()
                    else:
                        st.warning("請完整填寫金額與末五碼")
        else:
            st.success("🔓 **帳號狀態：【已開通】** —— 所有工具皆可使用。")
            uploaded_file = st.file_uploader(
                "📤 上傳您的資料檔案（支援 .xlsx / .xls / .csv）",
                type=["xlsx", "xls", "csv"],
            )
            if uploaded_file is None:
                st.info("請上傳檔案以開始分析。上傳後系統會自動進行 AI 欄位識別。")
            else:
                try:
                    if uploaded_file.name.lower().endswith('.csv'):
                        try:
                            df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                        except UnicodeDecodeError:
                            uploaded_file.seek(0)
                            df = pd.read_csv(uploaded_file, encoding='big5')
                    else:
                        df = pd.read_excel(uploaded_file)
                except Exception as e:
                    st.error(f"讀取檔案失敗：{e}")
                    st.stop()

                st.subheader(f"📄 原始檔案預覽（{len(df)} 列 × {len(df.columns)} 欄）")
                st.dataframe(df.head(10), use_container_width=True)

                st.divider()
                st.subheader("🤖 AI 欄位識別與品質報告")
                with st.spinner("AI 正在分析欄位類型…"):
                    quality = SmartCleaner.quality_score(df)
                    report = SmartCleaner.analyze_dataframe(df)
                    anomalies = SmartCleaner.detect_anomalies(df)

                c1, c2, c3 = st.columns(3)
                c1.metric("資料品質分數", f"{quality} / 100")
                c2.metric("偵測到的異常", f"{len(anomalies)} 項")
                c3.metric("重複列數", int(df.duplicated().sum()))

                st.markdown("**🔍 欄位分析**")
                st.dataframe(report.drop(columns=['_raw_type']), use_container_width=True)

                if anomalies:
                    st.markdown("**⚠️ 異常警告**")
                    st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

                st.divider()
                st.subheader("🧹 一鍵清理選項")
                with st.expander("進階設定", expanded=False):
                    opt_dup = st.checkbox("移除完全重複的列", value=True)
                    opt_col = st.checkbox("清理欄位名稱的頭尾空白", value=True)
                    opt_trim = st.checkbox("清理文字欄位的頭尾空白", value=True)
                    opt_phone = st.checkbox("標準化電話格式（移除 - 和空白）", value=True)
                    opt_date = st.checkbox("標準化日期格式為 YYYY-MM-DD", value=True)
                    opt_email = st.checkbox("Email 轉為小寫", value=True)
                    opt_fill = st.checkbox("填補空白值", value=False)
                    fill_val = st.text_input("填補值", value="", disabled=not opt_fill)

                if st.button("🚀 執行智慧清理", type="primary"):
                    options = {
                        'drop_duplicates': opt_dup,
                        'clean_columns': opt_col,
                        'trim_strings': opt_trim,
                        'normalize_phone': opt_phone,
                        'normalize_date': opt_date,
                        'normalize_email': opt_email,
                    }
                    if opt_fill:
                        options['fill_na'] = True
                        options['fill_value'] = fill_val

                    with st.spinner("正在清理資料…"):
                        df_clean, actions = SmartCleaner.clean_dataframe(df, options)
                        new_quality = SmartCleaner.quality_score(df_clean)

                    st.success(f"清理完成！品質分數：{quality} → **{new_quality}**")

                    if actions:
                        with st.expander("📋 執行紀錄", expanded=True):
                            for a in actions:
                                st.write(a)

                    st.markdown("**✅ 清理後預覽**")
                    st.dataframe(df_clean.head(10), use_container_width=True)

                    csv_bytes = df_clean.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    base = os.path.splitext(uploaded_file.name)[0]
                    st.download_button(
                        label="📥 下載清理後的 CSV",
                        data=csv_bytes,
                        file_name=f"{base}_cleaned.csv",
                        mime="text/csv",
                        type="primary",
                    )

                    execute(
                        "INSERT INTO usage_log (username, filename, rows, cols, actions) "
                        "VALUES (:u, :f, :r, :c, :a)",
                        {"u": current_user, "f": uploaded_file.name, "r": len(df_clean), "c": len(df_clean.columns), "a": ' | '.join(actions)},
                    )
                    execute(
                        "UPDATE users SET usage_count = usage_count + 1 WHERE username = :u",
                        {"u": current_user},
                    )
                    st.info("🔒 隱私保護：所有資料僅在記憶體中處理，不會寫入伺服器硬碟。")
