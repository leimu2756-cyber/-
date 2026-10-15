import os
import io
import time
import json
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


# ============================================================
# 0. 設定
# ============================================================
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

    .contact-box {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 24px;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin: 16px 0;
    }
    .contact-box h3 { color: white !important; margin-top: 0; margin-bottom: 8px; }
    .contact-box p { color: #f0f0f0; margin: 8px 0; font-size: 15px; }
    .contact-box a {
        display: inline-block;
        background: white;
        color: #4a3f8a !important;
        padding: 12px 28px;
        border-radius: 8px;
        text-decoration: none;
        font-weight: bold;
        font-size: 16px;
        margin-top: 12px;
    }
    .contact-box a:hover { transform: scale(1.05); }
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
# 工具函式
# ============================================================
def _is_phone_col(col_name, series):
    try:
        import re as _re
        name = str(col_name).lower()
        if any(kw in name for kw in ['電話', '手机', '手機', 'phone', 'tel', '手機號碼']):
            return True
        non_empty = series.dropna().astype(str).head(20)
        if len(non_empty) == 0:
            return False
        count = 0
        for v in non_empty:
            digits = _re.sub(r'\D', '', v)
            if 8 <= len(digits) <= 11:
                count += 1
        return count / len(non_empty) >= 0.6
    except Exception:
        return False


def _is_id_col(col_name, series):
    try:
        name = str(col_name).lower()
        if any(kw in name for kw in ['編號', '编号', 'id', '序號', '代號']):
            return True
        return False
    except Exception:
        return False


def _prepare_export_df(df):
    df_out = df.copy()
    for col in df_out.columns:
        try:
            if _is_phone_col(col, df_out[col]) or _is_id_col(col, df_out[col]):
                df_out[col] = df_out[col].apply(
                    lambda x: '' if pd.isna(x) else str(x)
                )
        except Exception:
            pass
    return df_out


def df_to_matrix(df):
    if df is None:
        return [], []
    headers = [str(c) for c in df.columns]
    rows = []
    n_rows = len(df)
    n_cols = len(df.columns)
    for i in range(n_rows):
        row = []
        for j in range(n_cols):
            try:
                v = df.iat[i, j]
            except Exception:
                v = ''
            row.append(v)
        rows.append(row)
    return headers, rows


def format_cell(v):
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return str(v)
    if isinstance(v, int):
        return str(v)
    return str(v)


def csv_escape(s):
    if ',' in s or '"' in s or '\n' in s or '\r' in s or ';' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def df_to_csv_bytes(df):
    df_prepared = _prepare_export_df(df)
    headers, rows = df_to_matrix(df_prepared)
    lines = []
    lines.append(','.join(csv_escape(h) for h in headers))
    for row in rows:
        cells = [csv_escape(format_cell(v)) for v in row]
        lines.append(','.join(cells))
    return ('\n'.join(lines)).encode('utf-8-sig')


def df_to_excel_multi(sheets_dict):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for name, df in sheets_dict.items():
            if df is None or len(df) == 0:
                continue
            df_prepared = _prepare_export_df(df)
            headers, rows = df_to_matrix(df_prepared)
            new_rows = []
            for row in rows:
                new_row = []
                for v in row:
                    if isinstance(v, float) and pd.notna(v) and v == int(v):
                        new_row.append(int(v))
                    else:
                        new_row.append(v)
                new_rows.append(new_row)
            df_out = pd.DataFrame(new_rows, columns=headers)
            sheet_name = str(name)[:31]
            df_out.to_excel(writer, index=False, sheet_name=sheet_name)
            try:
                ws = writer.sheets[sheet_name]
                for col_idx, col_name in enumerate(df_out.columns, 1):
                    is_phone = _is_phone_col(col_name, df_prepared[col_name])
                    is_id = _is_id_col(col_name, df_prepared[col_name])
                    if is_phone or is_id:
                        for row_idx in range(2, len(df_out) + 2):
                            cell = ws.cell(row=row_idx, column=col_idx)
                            cell.number_format = '@'
            except Exception:
                pass
    return buffer.getvalue()


def df_to_json_bytes(df):
    df_prepared = _prepare_export_df(df)
    headers, rows = df_to_matrix(df_prepared)
    records = []
    for row in rows:
        rec = {}
        for h, v in zip(headers, row):
            if isinstance(v, float) and pd.notna(v) and v == int(v):
                rec[h] = int(v)
            elif pd.isna(v):
                rec[h] = None
            else:
                rec[h] = v
        records.append(rec)
    return json.dumps(records, ensure_ascii=False, indent=2).encode('utf-8')


# ============================================================
# 清理前後對比
# ============================================================
def render_diff_view(df_before, df_after, max_rows=10):
    st.markdown("#### 🔍 逐格對比")
    try:
        before = df_before.head(max_rows).reset_index(drop=True)
        after = df_after.head(max_rows).reset_index(drop=True)
    except Exception as e:
        st.warning(f"對比失敗：{e}")
        return

    cols = list(after.columns)
    cols_compare = [c for c in cols if c != '疑似重複']

    html_parts = [
        '<div style="overflow-x:auto;font-size:12px;">',
        '<table style="width:100%;border-collapse:collapse;">',
    ]
    html_parts.append('<tr>')
    for c in cols_compare:
        html_parts.append(
            f'<th style="padding:6px;border:1px solid #ddd;'
            f'background:#f5f5f5;text-align:left;font-weight:600;">{c}</th>'
        )
    html_parts.append('</tr>')

    n = min(len(before), len(after))
    total_changes = 0
    for i in range(n):
        html_parts.append('<tr>')
        for c in cols_compare:
            try:
                b_val = str(before.iloc[i][c]) if c in before.columns else ''
                a_val = str(after.iloc[i][c]) if c in after.columns else ''
            except Exception:
                b_val, a_val = '', ''

            b_empty = b_val.strip() in ('', 'nan', 'None', 'NaN')
            a_empty = a_val.strip() in ('', 'nan', 'None', 'NaN')

            if b_val != a_val and not b_empty:
                total_changes += 1
                html_parts.append(
                    f'<td style="padding:6px;border:1px solid #ddd;background:#e8f5e9;">'
                    f'<span style="color:#999;text-decoration:line-through;font-size:11px;">{b_val}</span> '
                    f'<span style="color:#2e7d32;font-weight:bold;">→ {a_val}</span>'
                    f'</td>'
                )
            elif a_empty and not b_empty:
                total_changes += 1
                html_parts.append(
                    f'<td style="padding:6px;border:1px solid #ddd;background:#fff3e0;">'
                    f'<span style="color:#999;text-decoration:line-through;">{b_val}</span>'
                    f'</td>'
                )
            else:
                html_parts.append(
                    f'<td style="padding:6px;border:1px solid #ddd;">{a_val}</td>'
                )
        html_parts.append('</tr>')

    html_parts.append('</table></div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)
    st.caption(f"📊 前 {n} 行共 {total_changes} 處修改（綠色 = 修改後、灰色刪除線 = 修改前）")


# ============================================================
# 聯絡區塊 / 錯誤處理 / 上傳檢查
# ============================================================
def show_contact_box(compact=False):
    if compact:
        st.markdown("---")
        st.info(
            "💬 **需要客製化服務或遇到問題？**\n\n"
            "如果你的 Excel 格式比較特殊、洗不乾淨，或需要客製化資料處理，"
            "歡迎直接來信，我會**免費**為你評估。"
        )
        st.markdown(
            f'<a href="mailto:{ADMIN_EMAIL}?subject=資料清理需求" '
            f'target="_blank" style="display:inline-block;padding:10px 24px;'
            f'background:#4CAF50;color:white;border-radius:6px;'
            f'text-decoration:none;font-weight:bold;">'
            f'📧 寄信到 {ADMIN_EMAIL}</a>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="contact-box">'
            f'<h3>📮 需要客製化服務或遇到問題？</h3>'
            f'<p>不論是許願新功能、反映使用問題、或需要客製化資料處理服務，</p>'
            f'<p>都歡迎直接來信，我會親自回覆你。</p>'
            f'<p style="font-size:13px;opacity:0.85;">客製化服務免費評估，不需事先付費</p>'
            f'<a href="mailto:{ADMIN_EMAIL}?subject=資料清理需求" target="_blank">'
            f'📧 {ADMIN_EMAIL}</a>'
            f'</div>',
            unsafe_allow_html=True,
        )


def show_friendly_error(error, context=""):
    st.error(
        "⚠️ **這個檔案的格式比較特殊，系統暫時無法自動解析。**\n\n"
        "請檢查：\n"
        "- 檔案是否有加密（密碼保護）\n"
        "- 是否為正確的 Excel / CSV 格式"
    )
    with st.expander("🔍 技術細節（給工程師看）", expanded=False):
        if context:
            st.code(f"情境：{context}\n\n{error}")
        else:
            st.code(str(error))
    show_contact_box(compact=True)


def pre_validate_file(file):
    if file is None:
        return False, "沒有檔案"
    name = file.name.lower()
    if not name.endswith(('.xlsx', '.xls', '.csv')):
        return False, "僅支援 .xlsx / .xls / .csv 格式"
    try:
        size = len(file.getvalue())
    except Exception:
        size = 0
    if size == 0:
        return False, "檔案是空的（0 bytes）"
    if size > SINGLE_FILE_LIMIT:
        return False, f"檔案過大（{format_bytes(size)}），請縮小至 50MB 以內"
    return True, None


# ============================================================
# 1. 側邊欄
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
            "功能選單", ["🧹 資料清理工作台", "📮 客製化與反饋"],
            key="client_nav_radio",
        )
    if st.sidebar.button("登出", key="logout_btn"):
        st.session_state.update(logged_in=False, user_role=None, username=None)
        st.rerun()


# ============================================================
# 2. 未登入首頁
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
""")

    st.divider()
    show_contact_box(compact=False)


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
# 4. 客戶端
# ============================================================
elif st.session_state['user_role'] == 'client':
    current_user = st.session_state['username']

    if client_page == "📮 客製化與反饋":
        st.title("📮 客製化服務與意見反饋")
        st.markdown(f"""
歡迎來到這裡 👋

不論你是：
- 遇到 Excel 洗不乾淨、格式太特殊
- 想許願新功能
- 需要**客製化資料處理服務**

都可以直接來信，我會親自回覆你。
""")
        show_contact_box(compact=False)
        st.divider()
        st.markdown("### 📝 或填寫下方表單")
        st.caption("填寫後我會在後台看到，並用你留的聯絡方式回覆你。")

        with st.form("feedback_form", clear_on_submit=True):
            subject = st.text_input("主旨", placeholder="例如：需要合併 50 個分店的月報表")
            contact = st.text_input("你的聯絡方式（Line / Email / 電話）")
            message = st.text_area(
                "需求描述", height=200,
                placeholder="請描述：\n1. 你的資料長什麼樣子\n2. 你想達成什麼目標\n3. 目前怎麼手動處理\n4. 期望什麼時候完成",
            )
            if st.form_submit_button("📨 送出需求", type="primary"):
                if not message.strip():
                    st.warning("請至少填寫需求描述。")
                else:
                    try:
                        execute(
                            "INSERT INTO feedback (username, subject, message, contact) "
                            "VALUES (:u, :s, :m, :c)",
                            {"u": current_user, "s": subject or '（無主旨）', "m": message, "c": contact},
                        )
                        st.success("✅ 已送出！我會盡快回覆你。")
                        st.balloons()
                    except Exception as e:
                        st.error(f"送出失敗：{e}")

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
                st.caption(
                    "💡 提醒：如果 Excel 含有公式（如 `=A1*B1`），"
                    "系統無法自動計算。建議先在 Excel 打開檔案並存檔。"
                )
            else:
                is_valid, val_err = pre_validate_file(uploaded_file)
                if not is_valid:
                    st.error(f"❌ {val_err}")
                    show_contact_box(compact=True)
                    st.stop()

                try:
                    with st.spinner("正在讀取檔案…"):
                        df_raw, load_err = load_any_file(uploaded_file)
                except Exception as e:
                    show_friendly_error(e, context="讀取檔案")
                    st.stop()

                if load_err and df_raw is None:
                    st.error(f"❌ {load_err}")
                    show_contact_box(compact=True)
                    st.stop()

                if df_raw is None or len(df_raw) == 0:
                    st.error("⚠️ 檔案內容是空的，請確認上傳了正確的檔案。")
                    show_contact_box(compact=True)
                    st.stop()

                if load_err:
                    st.warning(f"⚠️ {load_err}")

                # 自動判斷標題
                try:
                    df = build_dataframe(df_raw, 0, 0, auto_mode=True)
                except Exception as e:
                    show_friendly_error(e, context="標題判斷")
                    st.stop()

                if df is None or len(df) == 0:
                    st.error("⚠️ 解析後沒有資料，請確認檔案內容。")
                    show_contact_box(compact=True)
                    st.stop()

                # 只在自動判斷失敗時才顯示手動設定
                auto_header_cols = all(
                    str(c).startswith('欄位') for c in df.columns
                ) if len(df.columns) > 0 else True

                if auto_header_cols:
                    st.warning("⚠️ 系統無法自動判斷表頭，請手動指定標題位置。")
                    col_s1, col_s2 = st.columns([1, 1])
                    with col_s1:
                        skip_n = st.number_input("跳過前幾行", min_value=0, max_value=100, value=0, key="single_skip")
                    with col_s2:
                        header_n = st.number_input("第幾行是標題（-1=無標題）", min_value=-1, max_value=100, value=0, key="single_header")
                    if st.button("🔄 重新解析", key="single_reparse"):
                        try:
                            df = build_dataframe(df_raw, skip_n, header_n, auto_mode=False)
                            st.rerun()
                        except Exception as e:
                            st.error(f"重新解析失敗：{e}")

                st.caption(f"📊 {len(df)} 列 × {len(df.columns)} 欄")

                # 行業模板（信心度 ≥ 70% 才顯示）
                try:
                    template_info = detect_template(df)
                    if template_info['template'] and template_info.get('confidence', 0) >= 0.7:
                        st.success(f"🎯 偵測到行業模板：**{template_info['template']}**")
                except Exception:
                    template_info = {'template': None, 'confidence': 0}

                # 重複資料處理方式（主選項）
                dup_mode_label = st.radio(
                    "🔁 重複資料處理方式",
                    ["僅標記重複（不刪除）", "自動去重合併"],
                    index=0,
                    key="single_dup_mode",
                    horizontal=True,
                )
                dup_mode = 'mark' if '僅標記' in dup_mode_label else 'drop'

                # 進階設定（收折）
                with st.expander("⚙️ 進階設定", expanded=False):
                    summary_action_map = {
                        "保留在資料中": "keep",
                        "完全移除": "remove",
                        "分離到另一張表": "separate",
                    }
                    summary_action = st.radio(
                        "彙總列處理方式",
                        list(summary_action_map.keys()),
                        index=2,
                        key="single_summary",
                    )

                    col_suggest = suggest_column_mapping(df)
                    if col_suggest:
                        st.markdown("**💡 系統建議的欄位對應**")
                        for k, v in col_suggest.items():
                            st.caption(f"- **{k}** → `{v}`")

                    st.markdown("**清理項目（預設全開）**")
                    col_1, col_2 = st.columns(2)
                    with col_1:
                        opt_date = st.checkbox("標準化日期格式", value=True, key="single_date")
                        opt_currency = st.checkbox("清理貨幣 / 中文數字", value=True, key="single_curr")
                    with col_2:
                        opt_phone = st.checkbox("標準化電話格式", value=True, key="single_phone")
                        opt_email = st.checkbox("Email 轉小寫", value=True, key="single_email")

                if st.button("🚀 開始清理", type="primary", key="single_clean_btn", use_container_width=True):
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
                            total_check=total_check,
                        )
                    except Exception as e:
                        show_friendly_error(e, context="清理資料")
                        st.stop()

                    status.text("步驟 2/3：產生報告…")
                    progress.progress(70)
                    status.text("步驟 3/3：完成！")
                    progress.progress(100)
                    status.empty()

                    # 總計警示
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
                                    f"原始：`{original:,}` ｜ 重算：`{recalc:,}` ｜ "
                                    f"差異：`{diff_str}`（{pct:.2f}%）"
                                )
                            else:
                                st.warning(
                                    f"⚠️ **總計有些微差異（{col_name}）** ｜ "
                                    f"原始：`{original:,}` ｜ 重算：`{recalc:,}` ｜ "
                                    f"差異：`{diff_str}`"
                                )

                    # 準備下載
                    try:
                        download_df = df_clean.copy()
                        summary_rows = build_summary_rows(df_clean, total_check)
                        if summary_rows is not None and len(summary_rows) > 0:
                            download_df = pd.concat(
                                [download_df, summary_rows], ignore_index=True
                            )
                    except Exception as e:
                        show_friendly_error(e, context="產生彙總列")
                        st.stop()

                    # 下載區
                    st.markdown("### ✅ 清理完成")
                    col_a, col_b, col_c = st.columns(3)
                    base = os.path.splitext(uploaded_file.name)[0]

                    try:
                        csv_bytes = df_to_csv_bytes(download_df)
                        with col_a:
                            st.download_button("📄 下載 CSV", csv_bytes,
                                              f"{base}_cleaned.csv", "text/csv",
                                              use_container_width=True, type="primary",
                                              key="single_dl_csv")
                    except Exception as e:
                        st.error(f"CSV 匯出失敗：{e}")

                    try:
                        sheets = {'清理後': download_df}
                        if summary_df is not None and len(summary_df) > 0:
                            sheets['原始總計'] = summary_df
                        if len(report_df) > 0:
                            sheets['欄位報告'] = report_df.drop(columns=['_raw_type'], errors='ignore')
                        if anomalies:
                            sheets['異常'] = pd.DataFrame(anomalies)
                        invalid_dates = stats.get('invalid_dates', [])
                        if invalid_dates:
                            inv_df = build_invalid_date_table(invalid_dates)
                            if len(inv_df) > 0:
                                sheets['無效日期'] = inv_df
                        dup_records = stats.get('duplicates_records', [])
                        if dup_records:
                            dup_df = build_duplicate_table(dup_records)
                            if len(dup_df) > 0:
                                sheets['疑似重複'] = dup_df
                        if total_check:
                            tct = build_total_summary_table(total_check)
                            if len(tct) > 0:
                                sheets['總計比對'] = tct

                        excel_bytes = df_to_excel_multi(sheets)
                        with col_b:
                            st.download_button("📊 下載 Excel", excel_bytes,
                                              f"{base}_cleaned.xlsx",
                                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                              use_container_width=True,
                                              key="single_dl_xlsx")
                    except Exception as e:
                        st.error(f"Excel 匯出失敗：{e}")

                    try:
                        json_bytes = df_to_json_bytes(download_df)
                        with col_c:
                            st.download_button("📋 下載 JSON", json_bytes,
                                              f"{base}_cleaned.json", "application/json",
                                              use_container_width=True,
                                              key="single_dl_json")
                    except Exception as e:
                        st.error(f"JSON 匯出失敗：{e}")

                    # 摘要
                    c1, c2, c3 = st.columns(3)
                    c1.metric("原始", f"{len(df)} 列")
                    removed = len(df) - len(df_clean)
                    c2.metric("清理後", f"{len(df_clean)} 列",
                              delta=f"-{removed}" if removed > 0 else "0")
                    c3.metric("品質分數", f"{quality_after} / 100",
                              delta=f"+{round(quality_after - quality_before, 1)}" if quality_after > quality_before else "0")

                    # 前後對比（主推）
                    with st.expander("🔍 清理前後對比（前 10 筆）", expanded=True):
                        render_diff_view(df, df_clean, max_rows=10)
                        if summary_rows is not None and len(summary_rows) > 0:
                            st.markdown("**下載檔案底部彙總**")
                            st.dataframe(summary_rows, use_container_width=True)

                    # 詳細報告（收折）
                    with st.expander("📊 詳細報告", expanded=False):
                        rep = build_clean_report(stats, total_check, template_info)
                        if len(rep) > 0:
                            st.dataframe(rep, use_container_width=True, hide_index=True)
                        else:
                            st.info("沒有需要處理的地方。")

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
                            st.warning(f"⚠️ 發現 {len(dup_records)} 筆疑似重複")
                            dup_df = build_duplicate_table(dup_records)
                            if len(dup_df) > 0:
                                st.dataframe(dup_df, use_container_width=True, hide_index=True)

                        st.markdown("**🤖 欄位識別報告**")
                        st.dataframe(report_df.drop(columns=['_raw_type'], errors='ignore'),
                                    use_container_width=True)

                        if anomalies:
                            st.markdown("**⚠️ 異常清單**")
                            st.dataframe(pd.DataFrame(anomalies), use_container_width=True)

                    # 寫入歷史
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

                try:
                    with st.spinner("正在讀取所有檔案…"):
                        files_data = []
                        for f in uploaded_files:
                            is_valid, val_err = pre_validate_file(f)
                            if not is_valid:
                                st.warning(f"跳過 {f.name}：{val_err}")
                                continue
                            df_raw, err = load_any_file(f)
                            if df_raw is None:
                                st.warning(f"跳過 {f.name}：{err}")
                                continue
                            try:
                                df_use = build_dataframe(df_raw, 0, 0, auto_mode=True)
                                files_data.append({'name': f.name, 'df': df_use})
                            except Exception as e:
                                st.warning(f"跳過 {f.name}：{e}")
                except Exception as e:
                    show_friendly_error(e, context="讀取多個檔案")
                    st.stop()

                if not files_data:
                    st.error("沒有可處理的檔案")
                    show_contact_box(compact=True)
                else:
                    try:
                        strategy_info = detect_merge_strategy(files_data)
                    except Exception as e:
                        show_friendly_error(e, context="偵測合併策略")
                        st.stop()

                    with st.expander("📋 各檔案欄位一覽", expanded=False):
                        for name, cols in strategy_info['all_cols'].items():
                            st.write(f"**{name}**：{', '.join(cols)}")

                    # 策略建議
                    if strategy_info['strategy'] == 'ask':
                        st.info("💡 偵測到共同欄位，可選「垂直堆疊」或「水平關聯」")
                        default_mode = 'join'
                    else:
                        default_mode = 'stack'

                    # 合併方式（橫向）
                    merge_mode = st.radio(
                        "🔗 合併方式",
                        ["垂直堆疊（上下接起來）", "水平關聯（用共同欄位接起來）"],
                        index=1 if default_mode == 'join' else 0,
                        key="merge_mode_radio",
                        horizontal=True,
                    )

                    use_join = "水平關聯" in merge_mode

                    if use_join:
                        if not strategy_info['common_cols']:
                            st.warning("⚠️ 沒有偵測到共同欄位，將改用垂直堆疊。")
                            use_join = False
                        else:
                            col_j1, col_j2, col_j3 = st.columns(3)
                            with col_j1:
                                suggested_key = suggest_join_key(files_data, strategy_info['common_cols'])
                                join_key = st.selectbox(
                                    "共同欄位",
                                    strategy_info['common_cols'],
                                    index=strategy_info['common_cols'].index(suggested_key) if suggested_key in strategy_info['common_cols'] else 0,
                                    key="merge_join_key",
                                )
                            with col_j2:
                                join_type_map = {
                                    "LEFT JOIN": "left",
                                    "INNER JOIN": "inner",
                                    "RIGHT JOIN": "right",
                                    "FULL OUTER JOIN": "outer",
                                }
                                join_type_label = st.selectbox(
                                    "JOIN 類型",
                                    list(join_type_map.keys()),
                                    index=0, key="merge_join_type",
                                )
                                join_type = join_type_map[join_type_label]
                            with col_j3:
                                base_file = st.selectbox(
                                    "以哪個為基準",
                                    [f['name'] for f in files_data],
                                    index=0, key="merge_base_file",
                                )
                            st.caption(f"💡 用「{join_key}」欄位，以「{base_file}」為基準做 {join_type.upper()} JOIN")

                    # 重複處理 + 進階設定
                    col_dup, col_adv = st.columns([2, 1])
                    with col_dup:
                        dup_mode_label = st.radio(
                            "🔁 重複資料處理",
                            ["僅標記重複（不刪除）", "自動去重合併"],
                            index=0, key="merge_dup_mode",
                            horizontal=True,
                        )
                        dup_mode = 'mark' if '僅標記' in dup_mode_label else 'drop'
                    with col_adv:
                        with st.expander("⚙️ 進階設定", expanded=False):
                            if use_join:
                                opt_keep_source = True
                                st.caption("✅ JOIN 自動保留來源")
                            else:
                                opt_keep_source = st.checkbox("保留來源檔案欄位", value=True, key="merge_keep")

                    if st.button("🚀 開始合併", type="primary", key="merge_btn", use_container_width=True):
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

                        try:
                            result = merge_files(files_data, merge_options)
                        except Exception as e:
                            show_friendly_error(e, context="合併檔案")
                            st.stop()

                        status.text("步驟 2/2：產生報告中…")
                        progress.progress(100)
                        status.empty()

                        if result.get('error'):
                            st.error(f"合併失敗：{result['error']}")
                            show_contact_box(compact=True)
                        else:
                            merged = result['merged_df']
                            stats = result['stats']

                            st.success(f"✅ 合併完成！共 {stats['files']} 個檔案，{len(merged)} 列")

                            col_a, col_b = st.columns(2)

                            # CSV 匯出（獨立處理）
                            csv_bytes = None
                            try:
                                csv_bytes = df_to_csv_bytes(merged)
                            except Exception as e:
                                st.warning(f"CSV 匯出失敗：{e}")

                            with col_a:
                                if csv_bytes is not None:
                                    st.download_button("📄 下載 CSV", csv_bytes, "merged.csv",
                                                      "text/csv", use_container_width=True, type="primary",
                                                      key="merge_dl_csv")
                            excel_bytes = None
                            try:
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
                                        })

                                sheets = {
                                    '合併明細': merged,
                                    '合併統計': pd.DataFrame([stats]).T.reset_index().rename(
                                        columns={'index': '項目', 0: '值'}
                                    ),
                                }
                                if result.get('anomalies'):
                                    sheets['異常清單'] = pd.DataFrame(result['anomalies'])
                                if total_rows:
                                    sheets['原始總計比對'] = pd.DataFrame(total_rows)

                                excel_bytes = df_to_excel_multi(sheets)
                            except Exception as e:
                                st.warning(f"Excel 匯出失敗：{e}")

                            with col_b:
                                if excel_bytes is not None:
                                    st.download_button("📊 下載 Excel", excel_bytes, "merged.xlsx",
                                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                      use_container_width=True,
                                                      key="merge_dl_xlsx")

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

                            display_rows = []
                            for info in result['files_info']:
                                for tc in info.get('total_check', []):
                                    orig = tc['summary_value']
                                    rec = tc['calculated_value']
                                    d = round(rec - orig, 2)
                                    d_str = f'+{d:,}' if d > 0 else f'{d:,}'
                                    display_rows.append({
                                        '檔案': info['file'],
                                        '欄位': tc['column'],
                                        '原始總計': orig,
                                        '重算總計': rec,
                                        '差額': d_str,
                                        '差額%': f"{abs(d) / max(rec, 1) * 100:.2f}%",
                                    })
                            if display_rows:
                                st.error("🚨 **各檔總計不一致**")
                                st.dataframe(pd.DataFrame(display_rows), use_container_width=True)

                            with st.expander("📋 合併結果預覽", expanded=True):
                                st.dataframe(merged.head(20), use_container_width=True)

                            if result.get('anomalies'):
                                with st.expander("⚠️ 異常清單", expanded=False):
                                    st.dataframe(pd.DataFrame(result['anomalies']), use_container_width=True)

                            show_contact_box(compact=True)

        # ====================================================
        # Tab 3：資料分析（簡化）
        # ====================================================
        with tab3:
            st.subheader("📊 資料分析")
            st.caption("上傳已清理的資料，自動產生視覺化圖表。")

            analytics_file = st.file_uploader(
                "上傳資料檔案（.xlsx / .xls / .csv）",
                type=["xlsx", "xls", "csv"],
                key="analytics_upload",
            )

            if analytics_file is None:
                st.info("👆 上傳檔案後，系統會自動產生分析圖表。")
            else:
                is_valid, val_err = pre_validate_file(analytics_file)
                if not is_valid:
                    st.error(f"❌ {val_err}")
                    show_contact_box(compact=True)
                    st.stop()

                try:
                    with st.spinner("正在讀取…"):
                        df_a, err = load_any_file(analytics_file)
                except Exception as e:
                    show_friendly_error(e, context="讀取分析檔案")
                    st.stop()

                if df_a is None:
                    st.error(f"讀取失敗：{err}")
                    show_contact_box(compact=True)
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

                    st.caption(f"📊 {len(df_a)} 列 × {len(df_a.columns)} 欄")
                    try:
                        render_analytics(df_a)
                    except Exception as e:
                        show_friendly_error(e, context="資料分析")
                    show_contact_box(compact=True)

        if st.session_state.get('history'):
            with st.sidebar.expander("📜 最近處理紀錄", expanded=False):
                for h in st.session_state['history']:
                    st.caption(f"• {h['file']}（{h['rows']} 列）")
