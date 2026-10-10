"""共用工具"""
import re
import pandas as pd
import numpy as np
from datetime import datetime


CN_NUM = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9,
    '壹': 1, '貳': 2, '參': 3, '叁': 3, '肆': 4, '伍': 5,
    '陸': 6, '柒': 7, '捌': 8, '玖': 9,
}

CN_UNIT = {
    '拾': 10, '佰': 100, '仟': 1000, '十': 10, '百': 100, '千': 1000,
    '萬': 10000, '万': 10000, '億': 100000000, '亿': 100000000,
}

CN_SUFFIXES = ['元整', '元正', '圓整', '元', '整', '圓', '圆', '圆整']

CN_MONEY_INDICATORS = [
    '壹', '貳', '參', '叁', '肆', '伍', '陸', '柒', '捌', '玖',
    '拾', '佰', '仟', '萬', '億', '元整',
]

EXCEL_ERRORS = [
    '#VALUE!', '#N/A', '#DIV/0!', '#REF!',
    '#NAME?', '#NULL!', '#NUM!', 'N/A', 'NULL',
]

NON_DATA_KEYWORDS = [
    '###', '===', '---', '系統警告', '報表結束', '資料嚴重損毀',
    '公司名稱', '備註：', '備註:',
]

SUMMARY_KEYWORDS = [
    '總計', '小計', '合計', '總和', '總結',
    'Total', 'Subtotal', 'Sum', 'Grand Total',
]

UNIT_SUFFIXES = ['分', '級', '级', '歲', '岁', '個', '个', '件', '顆', '颗',
                 '元', '塊', '块', '張', '张', '台', '組', '组', '人',
                 '次', '筆', '笔', '年', '月', '日', '小時', '小时']


# ==========================================================
# 標準欄位名稱與同義詞對照表
# ==========================================================
STANDARD_COLUMNS = {
    '日期': ['日期', '交易日期', '交易日', '交易時間', '交易时间', '下單日', '下單日期',
             '下单日期', '訂單日期', '订单日期', '記帳日', '時間', '时间',
             'Date', 'date', 'Time', 'time'],
    '產品': ['產品', '产品', '產品名稱', '产品名称', '品項', '品项', '項目', '项目',
             '商品', '商品名稱', '商品名称', '產品名', 'Item', 'item', 'Product', 'product'],
    '金額': ['金額', '金额', '銷售額', '销售额', '營業額', '营业额', '總價', '总价',
             '總金額', '总金额', '小計', '小计', '價錢', '价钱',
             'Amount', 'amount', 'Revenue', 'revenue', 'Total', 'total'],
    '業務': ['業務', '业务', '業務員', '业务员', '銷售員', '销售员', '負責人', '负责人'],
    '付款方式': ['付款方式', '支付方式', '付款', 'Payment', 'payment'],
    '備註': ['備註', '备注', '說明', '说明', 'Note', 'note', 'Memo', 'memo'],
    '分類': ['分類', '分类', '類別', '类别', '類型', '类型', 'Category', 'category'],
    '數量': ['數量', '数量', '訂購數量', '订购数量', '件數', '件数',
             'Quantity', 'quantity', 'Qty', 'qty'],
    '單價': ['單價', '单价', 'Unit Price', 'UnitPrice', '價格', '价格', 'Price', 'price'],
    '客戶': ['客戶', '客户', '客戶名稱', '客户名称', '客戶姓名', '客户姓名',
             '姓名', '買家', 'Customer', 'customer'],
    '電話': ['電話', '电话', '手機', '手机', '手機號碼', '手机号码',
             '聯絡電話', '联络电话', 'Phone', 'phone'],
    'Email': ['Email', 'email', 'E-mail', 'e-mail', '電子郵件', '电子邮箱', '信箱'],
    '地址': ['地址', '住址', 'Address', 'address'],
    '公司': ['公司', '公司名稱', '公司名称', 'Company', 'company'],
    '客戶ID': ['客戶ID', '客户ID', '客戶編號', '客户编号', 'CustomerID', 'customer_id'],
    '產品編號': ['產品編號', '产品编号', '商品編號', '商品编号', '品號', '品号', 'ProductID'],
    '訂單編號': ['訂單編號', '订单编号', '訂單號', '订单号', 'OrderID', 'order_id'],
}


def standardize_columns(df, enabled=True):
    """
    將同義欄位名稱統一為標準名稱
    例如：「交易日期」→「日期」、「品項」→「產品」
    避免衝突：若標準名稱已被使用，則不重複改名
    """
    if not enabled or df is None or len(df.columns) == 0:
        return df

    rename_map = {}
    used_std_names = set()

    # 第一輪：先標記已經使用標準名稱的欄位
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in STANDARD_COLUMNS:
            used_std_names.add(col_str)

    # 第二輪：把同義詞欄位改名
    for col in df.columns:
        col_str = str(col).strip()
        if col_str in STANDARD_COLUMNS:
            continue  # 已是標準名
        if col in rename_map:
            continue
        for std_name, synonyms in STANDARD_COLUMNS.items():
            if std_name in used_std_names:
                continue
            if col_str in synonyms:
                rename_map[col] = std_name
                used_std_names.add(std_name)
                break

    if rename_map:
        return df.rename(columns=rename_map)
    return df


def parse_chinese_number(text):
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    for suf in CN_SUFFIXES:
        if s.endswith(suf):
            s = s[:-len(suf)].strip()
            break
    if not s:
        return None
    total = 0
    section = 0
    current = 0
    has_any = False
    num_buffer = ''

    def flush_num_buffer():
        nonlocal total, num_buffer
        if num_buffer:
            try:
                total += int(num_buffer)
            except ValueError:
                pass
            num_buffer = ''

    for ch in s:
        if ch in CN_NUM:
            flush_num_buffer()
            current = CN_NUM[ch]
            has_any = True
        elif ch in CN_UNIT:
            flush_num_buffer()
            unit = CN_UNIT[ch]
            has_any = True
            if unit >= 10000:
                section = (section + current) * unit
                total += section
                section = 0
                current = 0
            else:
                if current == 0:
                    current = 1
                section += current * unit
                current = 0
        elif ch.isdigit():
            num_buffer += ch
            has_any = True
        elif ch in '., ':
            continue
        else:
            return None
    flush_num_buffer()
    if not has_any:
        return None
    return float(total + section + current)


def strip_unit_suffix(value):
    if pd.isna(value):
        return value
    s = str(value).strip()
    if not s:
        return value
    for suf in UNIT_SUFFIXES:
        if s.endswith(suf):
            inner = s[:-len(suf)].strip()
            if not inner:
                continue
            try:
                return float(inner)
            except ValueError:
                pass
            parsed = parse_chinese_number(inner)
            if parsed is not None:
                return parsed
            return value
    return value


def has_chinese_number(text):
    if text is None or pd.isna(text):
        return False
    s = str(text)
    return any(ch in CN_NUM or ch in CN_UNIT for ch in s)


def to_halfwidth(value):
    if pd.isna(value):
        return value
    result = []
    for ch in str(value):
        code = ord(ch)
        if code == 0x3000:
            result.append(' ')
        elif 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        else:
            result.append(ch)
    return ''.join(result)


def flatten_newlines(value):
    if pd.isna(value):
        return value
    s = str(value)
    s = s.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def validate_date(y, mo, d):
    try:
        if not (1 <= mo <= 12):
            return f"{y}-{mo:02d}-{d:02d}（無效日期）"
        if not (1 <= d <= 31):
            return f"{y}-{mo:02d}-{d:02d}（無效日期）"
        return pd.Timestamp(year=y, month=mo, day=d).strftime('%Y-%m-%d')
    except Exception:
        return f"{y}-{mo:02d}-{d:02d}（無效日期）"


def convert_minguo_to_western(value):
    """
    民國年 / 各種日期格式 → YYYY-MM-DD
    支援：
      2026/1/7、2026-01-07、115/1/7、115-01-07、1/7
      民國115年1月7日、115年1月7日、2026年1月7日
    """
    if pd.isna(value):
        return value
    s = str(value).strip()
    if s == '' or s.lower() == 'nan':
        return np.nan

    # 只有月/日（1/7）
    m = re.match(r'^(\d{1,2})[\-/](\d{1,2})$', s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return validate_date(datetime.now().year, mo, d)

    # 民國115年1月7日
    m = re.match(r'^民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if m:
        return validate_date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))

    # 2026年1月7日（4 位西元年，支援 1 或 2 位月日，含 01）
    m = re.match(r'^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if m:
        return validate_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 115年1月7日（2~3 位年份，視為民國）
    m = re.match(r'^(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if m:
        y = int(m.group(1))
        if 1 <= y <= 200:
            return validate_date(y + 1911, int(m.group(2)), int(m.group(3)))

    # 115/1/7 或 115-1-7（三位數年視為民國）
    m = re.match(r'^(\d{2,3})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
    if m:
        y = int(m.group(1))
        if 1 <= y <= 200:
            return validate_date(y + 1911, int(m.group(2)), int(m.group(3)))

    # 四位西元年（2026/1/7 或 2026-01-07）
    m = re.match(r'^(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
    if m:
        return validate_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    return value


def clean_currency_value(value):
    if pd.isna(value):
        return value
    s = str(value).strip()
    if s == '' or s.lower() == 'nan':
        return np.nan
    if has_chinese_number(s):
        parsed = parse_chinese_number(s)
        if parsed is not None:
            return parsed
    m = re.match(r'^\(([\d,\.]+)\)$', s)
    if m:
        try:
            return -float(m.group(1).replace(',', ''))
        except ValueError:
            return value
    cleaned = s
    for token in ['NT$', 'NT', 'nt$', 'nt', '$', ',', ' ', '元', '　']:
        cleaned = cleaned.replace(token, '')
    try:
        if cleaned in ('', '-'):
            return value
        return float(cleaned)
    except ValueError:
        return value


def normalize_phone(value):
    if pd.isna(value):
        return value
    s = str(value).strip()
    if not s:
        return value
    digits = re.sub(r'\D', '', s)
    if not digits:
        return value
    if not digits.startswith('0') and len(digits) == 9:
        digits = '0' + digits
    return digits


def is_phone_like(value):
    if pd.isna(value):
        return False
    s = str(value).strip()
    if not s:
        return False
    digits = re.sub(r'\D', '', s)
    if len(digits) < 8 or len(digits) > 11:
        return False
    if re.match(r'^09\d{8}$', digits):
        return True
    if re.match(r'^0\d{7,9}$', digits):
        return True
    if re.match(r'^9\d{8}$', digits):
        return True
    return False


def is_summary_row(row):
    try:
        values = [v for v in row.values if pd.notna(v)]
    except Exception:
        return False
    if not values:
        return False
    for v in values[:3]:
        s = str(v).strip()
        for kw in SUMMARY_KEYWORDS:
            if kw in s:
                return True
    return False


def is_non_data_row(row):
    try:
        values = [v for v in row.values if pd.notna(v)]
    except Exception:
        return False
    if len(values) == 0:
        return True
    try:
        row_str = ' '.join(str(v) for v in values)
    except Exception:
        return False
    cleaned = row_str.replace(',', '').replace(' ', '').replace('\t', '').strip()
    if cleaned == '':
        return True
    if len(cleaned) <= 1 and not cleaned.isalnum():
        return True
    for kw in NON_DATA_KEYWORDS:
        if kw in row_str:
            return True
    return False


def format_bytes(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def is_garbage_row(row):
    try:
        row_str = ' '.join(str(v) for v in row.values if pd.notna(v))
    except Exception:
        return False
    if not row_str.strip():
        return False
    for kw in ['###', '===', '---', '系統警告', '報表結束',
               '資料嚴重損毀', '公司名稱']:
        if kw in row_str:
            return True
    return False


def is_header_row(row):
    try:
        vals = list(row.values)
    except Exception:
        return False
    non_empty = [
        v for v in vals
        if pd.notna(v) and str(v).strip() not in ('', 'nan', 'None')
    ]
    if not non_empty or not vals:
        return False
    if len(non_empty) / len(vals) < 0.5:
        return False
    text_count = 0
    for v in non_empty:
        cleaned = (str(v).replace('.', '').replace('-', '')
                   .replace(',', '').replace('/', '').replace(' ', '').strip())
        if cleaned and not cleaned.isdigit():
            text_count += 1
    return text_count >= len(non_empty) * 0.6


def build_dataframe(df_raw, skip_n=0, header_n=0, auto_mode=True):
    if skip_n > 0:
        df_raw = df_raw.iloc[skip_n:].reset_index(drop=True)

    if auto_mode:
        garbage_idx = [
            i for i in range(len(df_raw))
            if is_garbage_row(df_raw.iloc[i])
        ]
        if garbage_idx:
            df_raw = df_raw.drop(index=garbage_idx).reset_index(drop=True)

        header_idx = None
        for i in range(min(len(df_raw), 10)):
            if is_header_row(df_raw.iloc[i]):
                header_idx = i
                break

        if header_idx is not None:
            df = df_raw.copy()
            new_cols = []
            for i, c in enumerate(df.iloc[header_idx].values):
                c_str = str(c).strip()
                if not c_str or c_str.lower() == 'nan':
                    c_str = f"欄位{i+1}"
                new_cols.append(c_str)
            df.columns = new_cols
            return df[header_idx+1:].reset_index(drop=True)
        else:
            df = df_raw.copy()
            df.columns = [f"欄位{i+1}" for i in range(len(df.columns))]
            return df
    else:
        if header_n == -1:
            df = df_raw.copy()
            df.columns = [f"欄位{i+1}" for i in range(len(df.columns))]
            return df
        elif 0 <= header_n < len(df_raw):
            df = df_raw.copy()
            new_cols = []
            for i, c in enumerate(df.iloc[header_n].values):
                c_str = str(c).strip()
                if not c_str or c_str.lower() == 'nan':
                    c_str = f"欄位{i+1}"
                new_cols.append(c_str)
            df.columns = new_cols
            return df[header_n+1:].reset_index(drop=True)
        else:
            df = df_raw.copy()
            df.columns = [f"欄位{i+1}" for i in range(len(df.columns))]
            return df
