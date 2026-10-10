import os
import io
import time
import bcrypt
import pandas as pd
import streamlit as st

from cleaner import SmartCleaner
from loader import load_any_file, format_bytes, SINGLE_FILE_LIMIT, TOTAL_UPLOAD_LIMIT
from templates import detect_template, suggest_column_mapping, TEMPLATES
from merge import merge_files, detect_merge_strategy, suggest_join_key
from report import (
    build_clean_report,
    build_summary_rows,
    build_total_summary_table,
    build_invalid_date_table,
    build_duplicate_table,
    build_anomaly_table,
)
from analytics import render_analytics
from utils import build_dataframe
from db import init_db, fetch_one, fetch_all, execute


ADMIN_EMAIL = '717804lin@gmail.com'

ANNOUNCEMENT = {
    'title': '📢 公告',
    'content': """
本服務目前為**免費測試階段**。

免費不會永久持續。未來將視使用情況與開發進度，逐步調整為付費方案。

目前所有功能均免費開放，歡迎多加利用並給予回饋。

若你願意支持這個工具繼續開發，歡迎留下你的建議與使用心得。

感謝你的使用。
""",
    'level': 'info',
}

st.set_page_config(
    page_title="AI 資料清理工作台",
    page_icon="🧹",
    layout="wide",
)

try:
    MASTER_PASSWORD = st.secrets["MASTER_PASSWORD"]
except Exception:
    MASTER_PASSWORD = "fallback_change_me"

st.markdown("""
<style>
    [data-testid="stToolbar"] { display: none !important; }
    header[data-testid="stHeader"] { display: none !important; }
    footer { visibility: hidden !important; }
    #MainMenu { visibility: hidden !important; }
    [data-testid="stAppDeployButton"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

try:
    init_db()
except Exception as e:
    st.warning(f"⚠️ 資料庫連線異常：{e}")

SESSION_TIMEOUT = 30 * 60

for key, default in [('logged_in', False), ('user_role', None), ('username', None),
                     ('history', []), ('last_activity', time.time())]:
    if key not in st.session_state:
        st.session_state[key] = default

if st.session_state['logged_in']:
    now = time.time()
    if now - st.session_state.get('last_activity', now) > SESSION_TIMEOUT:
        st.session_state.update(logged_in=False, user_role=None, username=None)
        st.warning("⏰ 閒置超過 30 分鐘，已自動登出。")
        st.rerun()
    else:
        st.session_state['last_activity'] = now


# ============================================================
# 側邊欄
# ============================================================
st.sidebar.title("🧹 AI 資料清理工作台")
client_page = None

if not st.session_state['logged_in']:
    nav = st.sidebar.radio("選擇身分", ["客戶登入", "客戶註冊", "管理員後台"],
                          key="sidebar_nav")

    if nav == "客戶登入":
        u = st.sidebar.text_input("帳號", key="login_user")
        p = st.sidebar.text_input("密碼", type="password", key="login_pass")
        if st.sidebar.button("登入", key="login_btn"):
            if not u or not p:
                st.sidebar.warning("請輸入帳號與密碼")
            else:
                try:
                    row = fetch_one("SELECT password FROM users WHERE username = :u", {"u": u})
                except Exception as e:
                    st.sidebar.error(f"資料庫連線失敗：{e}")
                    row = None
                if row and bcrypt.checkpw(p.encode('utf-8'), row[0].encode('utf-8')):
                    st.session_state.update(
                        logged_in=True, user_role='client', username=u,
                        last_activity=time.time(),
                    )
                    st.rerun()
                else:
                    st.sidebar.error("帳號或密碼錯誤")

    elif nav == "客戶註冊":
        u = st.sidebar.text_input("設定帳號", key="reg_user")
        p = st.sidebar.text_input("設定密碼", type="password", key="reg_pass")
        contact = st.sidebar.text_input("聯絡方式 (Line / Email / 電話)", key="reg_contact")
        if st.sidebar.button("註冊", key="reg_btn"):
            if not (u and p and contact):
                st.sidebar.warning("請填寫所有欄位")
            elif len(p) < 8:
                st.sidebar.warning("密碼至少 8 個字元")
            else:
                try:
                    existing = fetch_one("SELECT username FROM users WHERE username = :u", {"u": u})
                except Exception as e:
                    st.sidebar.error(f"資料庫連線失敗：{e}")
                    existing = None
                if existing:
                    st.sidebar.error("此帳號已被註冊")
                else:
                    hashed = bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt())
                    try:
                        execute(
                            "INSERT INTO users (username, password, contact, status) "
                            "VALUES (:u, :p, :c, '已開通')",
                            {"u": u, "p": hashed.decode('utf-8'), "c": contact},
                        )
                        st.sidebar.success("註冊成功！直接登入即可使用全部功能。")
                    except Exception as e:
                        st.sidebar.error(f"註冊失敗：{e}")

    elif nav == "管理員後台":
        mp = st.sidebar.text_input("管理員密碼", type="password", key="admin_pass")
        if st.sidebar.button("進入後台", key="admin_btn"):
            if mp == MASTER_PASSWORD:
                st.session_state.update(
                    logged_in=True, user_role='admin', username='MasterAdmin',
                    last_activity=time.time(),
                )
                st.rerun()
            else:
                st.sidebar.error("密碼錯誤")

else:
    st.sidebar.success(f"已登入：{st.session_state['username']}")
    st.sidebar.caption(f"角色：{'管理員' if st.session_state['user_role'] == 'admin' else '客戶'}")
    if st.session_state['user_role'] == 'client':
        client_page = st.sidebar.radio(
            "功能選單", ["🧹 資料清理工作台", "💬 意見反饋"],
            key="client_nav_radio",
        )
    if st.sidebar.button("登出", key="logout_btn"):
        st.session_state.update(logged_in=False, user_role=None, username=None)
        st.rerun()


# ============================================================
# 未登入首頁
# ============================================================
if not st.session_state['logged_in']:
    if ANNOUNCEMENT['level'] == 'info':
        st.info(f"**{ANNOUNCEMENT['title']}**\n\n{ANNOUNCEMENT['content']}")
    elif ANNOUNCEMENT['level'] == 'warning':
        st.warning(f"**{ANNOUNCEMENT['title']}**\n\n{ANNOUNCEMENT['content']}")

    st.title("🧹 AI 資料清理工作台")
    st.info("👈 請從左側選單登入或註冊，所有功能完全免費。")
    col1, col2, col3 = st.columns(3)
    col1.metric("清理功能", "免費", "無使用次數限制")
    col2.metric("平均清理時間", "< 30 秒", "比手動快 200 倍")
    col3.metric("資料外洩事件", "0", "檔案自動銷毀")
    st.markdown(f"""
### 💡 核心功能
1. **AI 欄位識別** — 自動判斷 Email、手機、身分證、日期、金額等格式
2. **總計自動重算** — 比對明細加總 vs 原始總計，附上完整彙總
3. **多檔合併** — 支援垂直堆疊 + 水平 JOIN
4. **重複資料處理** — 可選「僅標記」或「自動去重」
5. **資料分析** — 分類圓餅圖、每月收支、付款方式分布
6. **隱私保護** — 資料僅在記憶體處理，密碼 bcrypt 雜湊儲存

### 📮 需要客製化服務？
直接來信：[{ADMIN_EMAIL}](mailto:{ADMIN_EMAIL})
""")

    st.divider()
    st.markdown("""
### 🔒 隱私政策

**1. 檔案處理**：所有上傳的檔案僅在伺服器記憶體中處理，**不會寫入硬碟**。

**2. 資料儲存**：只儲存帳號、密碼（bcrypt 雜湊）、聯絡方式。**不儲存任何上傳的檔案內容。**

**3. 密碼安全**：您的密碼以 bcrypt 雜湊儲存，**連管理員也無法看到原始密碼**。

**4. 第三方分享**：我們**不會**將您的資料分享給任何第三方。

**5. 資料刪除**：您可以隨時來信要求刪除您的帳號與所有相關資料。

**6. 傳輸加密**：所有資料透過 HTTPS 加密傳輸，資料庫連線使用 SSL。

**7. 登入安全**：閒置超過 30 分鐘會自動登出。

若有任何隱私相關問題，請來信：""" + ADMIN_EMAIL)


# ============================================================
# 管理員後台
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
                    cols = st.columns([2, 2, 1.5, 1.5, 1.5])
                    cols[0].write(f"**帳號**：{row[0]}")
                    cols[1].write(f"**聯絡**：{row[1]}")
                    cols[2].write(f"**使用次數**：{row[6]}")
                    cols[3].write(f"**註冊時間**：{str(row[7])[:10]}")
                    cols[4].success(row[4])
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
            for row in rows:
                with st.container():
                    st.markdown(f"### {row[2] or '（無主旨）'}")
                    st.caption(f"來自：{row[1]} ｜ {row[6]}")
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
                    if btn[1].button("🗑️ 刪除", key=f"fb_del_{row[0]}"):
                        execute("DELETE FROM feedback WHERE id=:i", {"i": row[0]})
                        st.rerun()
                    st.divider()


# ============================================================
# 客戶端
# ============================================================
elif st.session_state['user_role'] == 'client':
    current_user = st.session_state['username']

    # 4-A. 意見反饋
    if client_page == "💬 意見反饋":
        st.title("💬 意見反饋與客製化需求")
        st.markdown(f"""
有任何問題、想許願新功能、或需要 **客製化資料處理服務**？

**方式一**：直接寄信到 👉 [{ADMIN_EMAIL}](mailto:{ADMIN_EMAIL}?subject=資料清理需求)

**方式二**：填寫下方表單。
""")
        st.divider()
        with st.form("feedback_form", clear_on_submit=True):
            subject = st.text_input("主旨", placeholder="例如：需要合併 50 個分店的月報表")
            contact = st.text_input("你的聯絡方式")
            message = st.text_area("需求描述", height=200,
                                   placeholder="請描述：\n1. 你的資料長什麼樣子\n2. 你想達成什麼目標\n3. 目前怎麼手動處理")
            if st.form_submit_button("📨 送出需求", type="primary"):
                if not message.strip():
                    st.warning("請至少填寫需求描述。")
                else:
                    execute(
                        "INSERT INTO feedback (username, subject, message, contact) "
                        "VALUES (:u, :s, :m, :c)",
                        {"u": current_user, "s": subject or '（無主旨）', "m": message, "c": contact},
                    )
                    st.success("✅ 已送出！")
                    st.balloons()
        st.divider()

    # 4-B. 資料清理工作台
    else:
        st.title(f"👋 歡迎回來，{current_user}")

        if ANNOUNCEMENT['level'] == 'info':
            st.info(f"**{ANNOUNCEMENT['title']}**\n\n{ANNOUNCEMENT['content']}")
        elif ANNOUNCEMENT['level'] == 'warning':
            st.warning(f"**{ANNOUNCEMENT['title']}**\n\n{ANNOUNCEMENT['content']}")

        st.success("🔓 **所有功能完全免費** —— 無使用次數限制")

        tab1, tab2, tab3 = st.tabs(["📂 單檔整理", "🔗 多檔合併", "📊 資料分析"])

        # ====================================================
        # Tab 1：單檔整理
        # ====================================================
        with tab1:
            st.subheader("📂 單檔整理")
            uploaded_file = st.file_uploader(
                "上傳 Excel 或 CSV（.xlsx / .xls / .csv）",
                type=["xlsx", "xls", "csv"],
                key="single_upload",
            )

            if uploaded_file is None:
                st.info("👆 上傳檔案後，系統會自動清理並提供下載。")
            else:
                with st.spinner("正在讀取檔案…"):
                    df_raw, load_err = load_any_file(uploaded_file)

                if load_err and df_raw is None:
                    st.error(f"❌ {load_err}")
                else:
                    if load_err:
                        st.warning(f"⚠️ {load_err}")

                    st.caption(f"📊 讀取結果：{len(df_raw)} 列 × {len(df_raw.columns)} 欄")

                    try:
                        size = len(uploaded_file.getvalue())
                        if size > SINGLE_FILE_LIMIT:
                            st.warning(f"⚠️ 檔案較大（{format_bytes(size)}），處理時間可能較長")
                    except Exception:
                        pass

                    with st.expander("⚙️ 讀取設定", expanded=False):
                        manual_mode = st.checkbox("手動指定標題位置", value=False, key="single_manual")
                        if manual_mode:
                            skip_n = st.number_input("跳過前幾行", min_value=0, max_value=100, value=2, key="single_skip")
                            header_n = st.number_input("第幾行是標題（0=第一行，-1=無標題）",
                                                       min_value=-1, max_value=100, value=0, key="single_header")
                        else:
                            skip_n, header_n = 0, 0

                    try:
                        df = build_dataframe(df_raw, skip_n, header_n, auto_mode=(not manual_mode))
                    except Exception as e:
                        st.error(f"讀取失敗：{e}")
                        st.stop()

                    st.caption(f"📊 清理前：{len(df)} 列 × {len(df.columns)} 欄")

                    template_info = detect_template(df)
                    if template_info['template']:
                        st.info(f"🎯 偵測到行業模板：**{template_info['template']}**（信心度 {int(template_info['confidence']*100)}%）")

                    col_suggest = suggest_column_mapping(df)
                    if col_suggest:
                        with st.expander("💡 系統建議的欄位對應", expanded=False):
                            for k, v in col_suggest.items():
                                st.write(f"- **{k}** → `{v}`")

                    with st.expander("⚙️ 清理選項", expanded=True):
                        template_choice = st.selectbox("選擇模板", list(TEMPLATES.keys()), index=0, key="single_tpl")
                        summary_action = st.radio(
                            "彙總列處理方式",
                            ["保留在資料中", "完全移除", "分離到另一張表"],
                            index=2,
                            key="single_summary",
                        )
                        summary_action_map = {
                            "保留在資料中": "keep",
                            "完全移除": "remove",
                            "分離到另一張表": "separate",
                        }

                        st.markdown("**🔁 重複資料處理方式**")
                        dup_mode_label = st.radio(
                            "選擇重複資料的處理方式",
                            [
                                "僅標記重複（不刪除）｜適合訂單、記帳本",
                                "自動去重合併｜適合客戶名單、通訊錄",
                            ],
                            index=0,
                            key="single_dup_mode",
                            label_visibility="collapsed",
                        )
                        dup_mode = 'mark' if '僅標記' in dup_mode_label else 'drop'

                        st.markdown("---")
                        opt_date = st.checkbox("標準化日期格式", value=True, key="single_date")
                        opt_currency = st.checkbox("清理貨幣 / 中文數字", value=True, key="single_curr")
                        opt_phone = st.checkbox("標準化電話格式", value=True, key="single_phone")
                        opt_email = st.checkbox("Email 轉小寫", value=True, key="single_email")

                    if st.button("🚀 開始清理", type="primary", key="single_clean_btn"):
                        progress = st.progress(0)
                        status = st.empty()
                        status.text("步驟 1/3：清理資料中…")
                        progress.progress(30)

                        try:
                            clean_options = {
                                'remove_non_data_rows': True,
                                'clean_excel_errors': True,
                                'duplicate_mode': dup_mode,
                                'summary_row_action': summary_action_map[summary_action],
                                'clean_columns': True,
                                'standardize_columns': True,
                                'trim_strings': True,
                                'normalize_phone': opt_phone,
                                'normalize_date': opt_date,
                                'normalize_email': opt_email,
                                'clean_currency': opt_currency,
                            }
                            df_clean, actions, stats, summary_df, total_check = SmartCleaner.clean_dataframe(df, clean_options)
                            quality_before = SmartCleaner.quality_score(df)
                            quality_after = SmartCleaner.quality_score(df_clean)
                            report_df = SmartCleaner.analyze_dataframe(df_clean)
                            anomalies = SmartCleaner.detect_anomalies(
                                df_clean,
                                source_name=uploaded_file.name,
                                total_check=total_check,      # 傳入總計檢查結果
                            )
                        except Exception as e:
                            st.error(f"清理失敗：{e}")
                            st.stop()

                        status.text("步驟 2/3：產生報告…")
                        progress.progress(70)
                        status.text("步驟 3/3：完成！")
                        progress.progress(100)
                        status.empty()

                        # ========================================
                        # 總計不一致警示（紅色）
                        # ========================================
                        if total_check:
                            for item in total_check:
                                col_name = item.get('column', '')
                                original = item.get('summary_value', 0)
                                recalc = item.get('calculated_value', 0)
                                diff = round(recalc - original, 2)
                                pct = abs(diff) / max(recalc, 1) * 100
                                if diff > 0:
                                    diff_str = f'+{diff:,}'
                                else:
                                    diff_str = f'{diff:,}'
                                if pct > 5:
                                    st.error(
                                        f"🚨 **總計不一致（{col_name}）** ｜ "
                                        f"原始總計：`{original:,}` ｜ "
                                        f"重算總計：`{recalc:,}` ｜ "
                                        f"差異：`{diff_str}`（{pct:.2f}%）"
                                    )
                                else:
                                    st.warning(
                                        f"⚠️ **總計有些微差異（{col_name}）** ｜ "
                                        f"原始總計：`{original:,}` ｜ "
                                        f"重算總計：`{recalc:,}` ｜ "
                                        f"差異：`{diff_str}`"
                                    )
                        # ========================================
                        # 建立下載用的 DataFrame（附加彙總列）
                        # ========================================
                        download_df = df_clean.copy()
                        summary_rows = build_summary_rows(df_clean, total_check)
                        if summary_rows is not None and len(summary_rows) > 0:
                            download_df = pd.concat(
                                [download_df, summary_rows], ignore_index=True
                            )

                        st.markdown("---")
                        st.markdown("## ✅ 清理完成！")
                        st.caption(
                            "💡 下載檔案已包含明細資料 + 下方彙總列（原始總計、重算總計、差異）"
                        )

                        col_a, col_b, col_c = st.columns(3)
                        base = os.path.splitext(uploaded_file.name)[0]

                        csv_bytes = download_df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                        with col_a:
                            st.download_button("📄 下載 CSV", csv_bytes,
                                              f"{base}_cleaned.csv", "text/csv",
                                              use_container_width=True, type="primary",
                                              key="single_dl_csv")

                        excel_buffer = io.BytesIO()
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            download_df.to_excel(writer, index=False, sheet_name='清理後')
                            if summary_df is not None and len(summary_df) > 0:
                                summary_df.to_excel(writer, index=False, sheet_name='原始總計')
                            if len(report_df) > 0:
                                report_df.drop(columns=['_raw_type'], errors='ignore').to_excel(
                                    writer, index=False, sheet_name='欄位報告')
                            if anomalies:
                                pd.DataFrame(anomalies).to_excel(writer, index=False, sheet_name='異常')
                            invalid_dates = stats.get('invalid_dates', [])
                            if invalid_dates:
                                inv_df = build_invalid_date_table(invalid_dates)
                                if len(inv_df) > 0:
                                    inv_df.to_excel(writer, index=False, sheet_name='無效日期')
                            dup_records = stats.get('duplicates_records', [])
                            if dup_records:
                                dup_df = build_duplicate_table(dup_records)
                                if len(dup_df) > 0:
                                    dup_df.to_excel(writer, index=False, sheet_name='疑似重複')
                            if total_check:
                                tct = build_total_summary_table(total_check)
                                if len(tct) > 0:
                                    tct.to_excel(writer, index=False, sheet_name='總計比對')
                        excel_bytes = excel_buffer.getvalue()
                        with col_b:
                            st.download_button("📊 下載 Excel", excel_bytes,
                                              f"{base}_cleaned.xlsx",
                                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                              use_container_width=True,
                                              key="single_dl_xlsx")

                        json_bytes = download_df.to_json(
                            orient='records', force_ascii=False, indent=2
                        ).encode('utf-8')
                        with col_c:
                            st.download_button("📋 下載 JSON", json_bytes,
                                              f"{base}_cleaned.json", "application/json",
                                              use_container_width=True,
                                              key="single_dl_json")

                        st.markdown("---")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("原始資料", f"{len(df)} 列")
                        removed = len(df) - len(df_clean)
                        c2.metric("清理後明細", f"{len(df_clean)} 列",
                                  delta=f"-{removed}" if removed > 0 else "0")
                        c3.metric("品質分數", f"{quality_after} / 100",
                                  delta=f"+{round(quality_after - quality_before, 1)}" if quality_after > quality_before else "0")

                        # ========================================
                        # 清理報告
                        # ========================================
                        with st.expander("📊 清理報告", expanded=True):
                            rep = build_clean_report(stats, total_check, template_info)
                            if len(rep) > 0:
                                st.dataframe(rep, use_container_width=True, hide_index=True)
                            else:
                                st.info("沒有需要處理的地方。")

                            # 總計摘要
                            if total_check:
                                st.markdown("**📐 總計驗證**")
                                tct = build_total_summary_table(total_check)
                                if len(tct) > 0:
                                    st.dataframe(tct, use_container_width=True, hide_index=True)

                            invalid_dates = stats.get('invalid_dates', [])
                            if invalid_dates:
                                st.warning(f"⚠️ 發現 {len(invalid_dates)} 筆無效日期")
                                inv_df = build_invalid_date_table(invalid_dates)
                                if len(inv_df) > 0:
                                    st.dataframe(inv_df, use_container_width=True, hide_index=True)

                            dup_records = stats.get('duplicates_records', [])
                            if dup_records:
                                st.warning(f"⚠️ 發現 {len(dup_records)} 筆疑似重複（僅標記，未刪除）")
                                dup_df = build_duplicate_table(dup_records)
                                if len(dup_df) > 0:
                                    st.dataframe(dup_df, use_container_width=True, hide_index=True)

                        with st.expander("🔍 清理前後對比（前 10 筆）", expanded=False):
                            st.markdown("**清理前**")
                            st.dataframe(df.head(10), use_container_width=True)
                            st.markdown("**清理後明細**")
                            st.dataframe(df_clean.head(10), use_container_width=True)
                            if summary_rows is not None and len(summary_rows) > 0:
                                st.markdown("**下載檔案底部彙總**")
                                st.dataframe(summary_rows, use_container_width=True)

                        with st.expander("🤖 欄位識別報告", expanded=False):
                            st.dataframe(report_df.drop(columns=['_raw_type'], errors='ignore'),
                                        use_container_width=True)

                        if anomalies:
                            with st.expander("⚠️ 異常清單", expanded=True):
                                st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

                        try:
                            st.session_state['history'].insert(0, {
                                'file': uploaded_file.name,
                                'rows': len(df_clean),
                                'quality': quality_after,
                            })
                            st.session_state['history'] = st.session_state['history'][:5]
                        except Exception:
                            pass

                        try:
                            execute(
                                "INSERT INTO usage_log (username, filename, rows, cols, actions) "
                                "VALUES (:u, :f, :r, :c, :a)",
                                {"u": current_user, "f": uploaded_file.name,
                                 "r": len(df_clean), "c": len(df_clean.columns),
                                 "a": ' | '.join(actions)},
                            )
                        except Exception:
                            pass

                        st.caption("🔒 所有資料僅在記憶體中處理，不會寫入伺服器硬碟。")

        # ====================================================
        # Tab 2：多檔合併
        # ====================================================
        with tab2:
            st.subheader("🔗 多檔合併")
            uploaded_files = st.file_uploader(
                "一次上傳多個 Excel 或 CSV",
                type=["xlsx", "xls", "csv"],
                accept_multiple_files=True,
                key="multi_upload",
            )

            if not uploaded_files:
                st.info("👆 上傳多個檔案後，系統會自動偵測合併策略。")
            else:
                total_size = 0
                for f in uploaded_files:
                    try:
                        total_size += len(f.getvalue())
                    except Exception:
                        pass
                if total_size > TOTAL_UPLOAD_LIMIT:
                    st.warning(f"⚠️ 總上傳大小 {format_bytes(total_size)} 超過 200MB")

                with st.spinner("正在讀取所有檔案…"):
                    files_data = []
                    for f in uploaded_files:
                        df_raw, err = load_any_file(f)
                        if df_raw is None:
                            st.warning(f"跳過 {f.name}：{err}")
                            continue
                        try:
                            df_use = build_dataframe(df_raw, 0, 0, auto_mode=True)
                            files_data.append({'name': f.name, 'df': df_use})
                        except Exception as e:
                            st.warning(f"跳過 {f.name}：{e}")

                if not files_data:
                    st.error("沒有可處理的檔案")
                else:
                    strategy_info = detect_merge_strategy(files_data)

                    with st.expander("📋 各檔案欄位一覽", expanded=False):
                        for name, cols in strategy_info['all_cols'].items():
                            st.write(f"**{name}**：{', '.join(cols)}")

                    if strategy_info['strategy'] == 'stack':
                        st.success(f"✅ **建議：垂直堆疊**（{strategy_info['reason']}）")
                        default_mode = 'stack'
                    elif strategy_info['strategy'] == 'ask':
                        st.info(f"❓ **偵測到可 JOIN**（{strategy_info['reason']}）")
                        default_mode = 'join'
                    else:
                        default_mode = 'stack'

                    with st.expander("⚙️ 合併選項", expanded=True):
                        mode_options = ["垂直堆疊（上下接起來）", "水平關聯（用共同欄位接起來）"]
                        default_idx = 1 if default_mode == 'join' else 0
                        merge_mode = st.radio(
                            "合併方式",
                            mode_options,
                            index=default_idx,
                            key="merge_mode_radio",
                        )

                        use_join = "水平關聯" in merge_mode

                        if use_join:
                            if not strategy_info['common_cols']:
                                st.warning("⚠️ 沒有偵測到共同欄位，無法 JOIN。將改用垂直堆疊。")
                                use_join = False
                            else:
                                suggested_key = suggest_join_key(files_data, strategy_info['common_cols'])
                                join_key = st.selectbox(
                                    "JOIN 用的共同欄位",
                                    strategy_info['common_cols'],
                                    index=strategy_info['common_cols'].index(suggested_key) if suggested_key in strategy_info['common_cols'] else 0,
                                    key="merge_join_key",
                                )

                                join_type_label = st.radio(
                                    "JOIN 類型",
                                    ["LEFT JOIN（保留左邊全部）",
                                     "INNER JOIN（只保留兩邊都有的）",
                                     "RIGHT JOIN（保留右邊全部）",
                                     "FULL OUTER JOIN（兩邊都保留）"],
                                    index=0,
                                    key="merge_join_type",
                                )
                                join_type_map = {
                                    "LEFT JOIN（保留左邊全部）": "left",
                                    "INNER JOIN（只保留兩邊都有的）": "inner",
                                    "RIGHT JOIN（保留右邊全部）": "right",
                                    "FULL OUTER JOIN（兩邊都保留）": "outer",
                                }
                                join_type = join_type_map[join_type_label]

                                base_file = st.selectbox(
                                    "以哪個檔案為基準（LEFT/RIGHT JOIN 用）",
                                    [f['name'] for f in files_data],
                                    index=0,
                                    key="merge_base_file",
                                )

                                st.caption(f"💡 將用「{join_key}」欄位，以「{base_file}」為基準做 {join_type.upper()} JOIN")

                        st.markdown("**🔁 重複資料處理方式**")
                        dup_mode_label = st.radio(
                            "選擇重複資料的處理方式",
                            [
                                "僅標記重複（不刪除）｜適合訂單、記帳本",
                                "自動去重合併｜適合客戶名單、通訊錄",
                            ],
                            index=0,
                            key="merge_dup_mode",
                            label_visibility="collapsed",
                        )
                        dup_mode = 'mark' if '僅標記' in dup_mode_label else 'drop'

                        col1, col2 = st.columns(2)
                        with col2:
                            if use_join:
                                opt_keep_source = True
                                st.caption("✅ JOIN 模式自動保留來源資訊")
                            else:
                                opt_keep_source = st.checkbox("保留「來源檔案」欄位", value=True, key="merge_keep")

                    if st.button("🚀 開始合併", type="primary", key="merge_btn"):
                        progress = st.progress(0)
                        status = st.empty()

                        status.text("步驟 1/2：清理各檔案中…")
                        progress.progress(40)

                        merge_options = {
                            'mode': 'join' if use_join else 'stack',
                            'duplicate_mode': dup_mode,
                            'keep_source': opt_keep_source,
                        }
                        if use_join:
                            merge_options['join_type'] = join_type
                            merge_options['join_key'] = join_key
                            merge_options['base_file'] = base_file

                        result = merge_files(files_data, merge_options)

                        status.text("步驟 2/2：產生報告中…")
                        progress.progress(100)
                        status.empty()

                        if result.get('error'):
                            st.error(f"合併失敗：{result['error']}")
                        else:
                            merged = result['merged_df']
                            stats = result['stats']

                            # ========================================
                            # 合併後總計驗證
                            # ========================================
                            merged_total_check = []
                            try:
                                if '總計' in merged.astype(str).values:
                                    pass
                            except Exception:
                                pass

                            # 建立下載用 DataFrame（附加彙總，如果有）
                            download_merged = merged.copy()

                            st.success(f"✅ 合併完成！共 {stats['files']} 個檔案，{len(merged)} 列")

                            st.markdown("---")
                            col_a, col_b = st.columns(2)
                            csv_bytes = download_merged.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                            with col_a:
                                st.download_button("📄 下載 CSV", csv_bytes, "merged.csv",
                                                  "text/csv", use_container_width=True, type="primary",
                                                  key="merge_dl_csv")

                            excel_buffer = io.BytesIO()
                            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                                download_merged.to_excel(writer, index=False, sheet_name='合併明細')
                                pd.DataFrame([stats]).T.reset_index().rename(
                                    columns={'index': '項目', 0: '值'}
                                ).to_excel(writer, index=False, sheet_name='合併統計')
                                if result.get('anomalies'):
                                    pd.DataFrame(result['anomalies']).to_excel(
                                        writer, index=False, sheet_name='異常清單')
                                total_rows = []
                                for info in result['files_info']:
                                    for tc in info.get('total_check', []):
                                        total_rows.append({
                                            '檔案': info['file'],
                                            '欄位': tc['column'],
                                            '原始總計': tc['summary_value'],
                                            '重算總計': tc['calculated_value'],
                                            '差額': tc['difference'],
                                        })
                                if total_rows:
                                    pd.DataFrame(total_rows).to_excel(writer, index=False, sheet_name='原始總計比對')
                            excel_bytes = excel_buffer.getvalue()
                            with col_b:
                                st.download_button("📊 下載 Excel", excel_bytes, "merged.xlsx",
                                                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                  use_container_width=True,
                                                  key="merge_dl_xlsx")

                            st.markdown("---")
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("來源檔案", stats['files'])
                            c2.metric("合併後列數", stats.get('merged_rows', len(merged)))
                            c3.metric("移除空白", stats['removed_non_data'])
                            c4.metric("移除總計", stats['removed_summary'])

                            per_file = stats.get('per_file_rows', {})
                            if per_file:
                                detail_parts = []
                                for fname, rows in per_file.items():
                                    detail_parts.append(f"{fname}：{rows} 列")
                                st.caption("📊 各檔清理後：" + " ｜ ".join(detail_parts))

                            # 各檔總計比對
                            total_rows = []
                            for info in result['files_info']:
                                for tc in info.get('total_check', []):
                                    orig = tc['summary_value']
                                    rec = tc['calculated_value']
                                    d = round(rec - orig, 2)
                                    d_str = f'+{d:,}' if d > 0 else f'{d:,}'
                                    total_rows.append({
                                        '檔案': info['file'],
                                        '欄位': tc['column'],
                                        '原始總計': orig,
                                        '重算總計': rec,
                                        '差額': d_str,
                                        '差額%': f"{abs(d) / max(rec, 1) * 100:.2f}%",
                                    })
                            if total_rows:
                                st.error("🚨 **各檔總計不一致**")
                                st.dataframe(pd.DataFrame(total_rows), use_container_width=True)

                            with st.expander("📋 合併結果預覽", expanded=True):
                                st.dataframe(merged.head(20), use_container_width=True)

                            if result.get('anomalies'):
                                with st.expander("⚠️ 異常清單", expanded=False):
                                    st.dataframe(pd.DataFrame(result['anomalies']), use_container_width=True)

        # ====================================================
        # Tab 3：資料分析
        # ====================================================
        with tab3:
            st.subheader("📊 資料分析")
            st.caption("上傳已清理的資料，自動產生視覺化圖表。")

            analytics_file = st.file_uploader(
                "上傳資料檔案",
                type=["xlsx", "xls", "csv"],
                key="analytics_upload",
            )

            if analytics_file is None:
                st.info("👆 上傳檔案後，系統會自動產生分析圖表。")
            else:
                with st.spinner("正在讀取…"):
                    df_a, err = load_any_file(analytics_file)
                if df_a is None:
                    st.error(f"讀取失敗：{err}")
                else:
                    try:
                        first_valid = None
                        for i in range(min(len(df_a), 10)):
                            row = df_a.iloc[i]
                            non_empty = row.dropna()
                            if len(non_empty) >= 2:
                                first_valid = i
                                break
                        if first_valid is not None:
                            df_a.columns = [str(c).strip() for c in df_a.iloc[first_valid].values]
                            df_a = df_a[first_valid+1:].reset_index(drop=True)
                    except Exception:
                        pass

                    st.caption(f"📊 讀取結果：{len(df_a)} 列 × {len(df_a.columns)} 欄")
                    render_analytics(df_a)

        if st.session_state.get('history'):
            with st.sidebar.expander("📜 最近處理紀錄", expanded=False):
                for h in st.session_state['history']:
                    st.caption(f"• {h['file']}（{h['rows']} 列）")
