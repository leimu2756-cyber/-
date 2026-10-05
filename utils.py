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
    try:
        return float(s)
    except ValueError:
        pass
    total = section = current = 0
    has_any = False
    for ch in s:
        if ch in CN_NUM:
            current = CN_NUM[ch]
            has_any = True
        elif ch in CN_UNIT:
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
        else:
            return None
    if not has_any:
        return None
    return float(total + section + current)


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
    if pd.isna(value):
        return value
    s = str(value).strip()
    if s == '' or s.lower() == 'nan':
        return np.nan

    m = re.match(r'^(\d{1,2})[\-/](\d{1,2})$', s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return validate_date(datetime.now().year, mo, d)

    m = re.match(r'^民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if m:
        return validate_date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))

    m = re.match(r'^(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if m:
        y = int(m.group(1))
        if 1 <= y <= 200:
            return validate_date(y + 1911, int(m.group(2)), int(m.group(3)))

    m = re.match(r'^(\d{2,3})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
    if m:
        y = int(m.group(1))
        if 1 <= y <= 200:
            return validate_date(y + 1911, int(m.group(2)), int(m.group(3)))

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

    if any(ind in s for ind in CN_MONEY_INDICATORS):
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


# ==========================================================
# 標題 / 垃圾行偵測（從 app.py 移過來）
# ==========================================================
def is_garbage_row(row):
    """判斷是否為垃圾行"""
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
    """判斷是否像表頭"""
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
    """
    從原始 DataFrame 建立最終 DataFrame
    - skip_n: 跳過前幾行
    - header_n: 手動模式下第幾行是標題（-1 = 無標題）
    - auto_mode: 自動偵測
    """
    if skip_n > 0:
        df_raw = df_raw.iloc[skip_n:].reset_index(drop=True)

    if auto_mode:
        # 移除垃圾行
        garbage_idx = [
            i for i in range(len(df_raw))
            if is_garbage_row(df_raw.iloc[i])
        ]
        if garbage_idx:
            df_raw = df_raw.drop(index=garbage_idx).reset_index(drop=True)

        # 從前 10 行找表頭
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
