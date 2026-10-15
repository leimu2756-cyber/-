"""檔案讀取模組（含編碼 + 分隔符自動判定）"""
import io
import csv as csv_module
import pandas as pd
from collections import Counter

try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

from utils import format_bytes


SINGLE_FILE_LIMIT = 50 * 1024 * 1024
TOTAL_UPLOAD_LIMIT = 200 * 1024 * 1024
ROW_WARNING_LIMIT = 100000


class LoadError(Exception):
    pass


def _detect_encoding(raw_bytes):
    """自動判定編碼（台灣常見順序：utf-8-sig → utf-8 → big5 → cp950）"""
    # 先檢查 BOM
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    if raw_bytes.startswith(b'\xff\xfe'):
        return 'utf-16-le'
    if raw_bytes.startswith(b'\xfe\xff'):
        return 'utf-16-be'

    # 用 chardet 判斷
    if HAS_CHARDET:
        try:
            sample = raw_bytes[:200000]  # 只取前 200KB 判斷
            result = chardet.detect(sample)
            enc = result.get('encoding')
            confidence = result.get('confidence', 0)
            if enc and confidence >= 0.7:
                # 標準化名稱
                enc_lower = enc.lower()
                if 'big5' in enc_lower or 'cp950' in enc_lower:
                    return 'big5'
                if 'utf-8' in enc_lower:
                    return 'utf-8-sig'
                return enc
        except Exception:
            pass

    # fallback：按順序嘗試
    for enc in ['utf-8-sig', 'utf-8', 'big5', 'cp950']:
        try:
            raw_bytes.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return 'utf-8-sig'


def _detect_delimiter(text):
    """自動判定分隔符（, ; \\t |）"""
    # 取前 20 行
    lines = [line for line in text.splitlines() if line.strip()][:20]
    if not lines:
        return ','

    candidates = [',', ';', '\t', '|']
    best_delim = ','
    best_score = -1

    for delim in candidates:
        # 用 csv.reader 嘗試解析
        try:
            rows = list(csv_module.reader(lines, delimiter=delim))
        except Exception:
            continue

        if not rows:
            continue

        # 計算每行欄位數的「一致性」
        col_counts = [len(r) for r in rows]
        if not col_counts:
            continue

        most_common = Counter(col_counts).most_common(1)[0]
        count, freq = most_common

        # 欄位數至少要 >= 2，且一致性越高越好
        if count < 2:
            continue

        score = freq * count  # 一致性 × 欄位數
        if score > best_score:
            best_score = score
            best_delim = delim

    return best_delim


def _read_csv_robust(file, encoding=None, delimiter=None):
    """
    穩健的 CSV 讀取：
    1. 自動判定編碼（若未指定）
    2. 自動判定分隔符（若未指定）
    3. 用 csv 模組逐行讀取
    4. 用「眾數」欄位數對齊
    """
    try:
        file.seek(0)
        raw = file.read()
    except Exception:
        return None

    if isinstance(raw, bytes):
        # 判定編碼
        enc = encoding or _detect_encoding(raw)
        try:
            text = raw.decode(enc, errors='replace')
        except (UnicodeDecodeError, LookupError):
            text = raw.decode('utf-8-sig', errors='replace')
    else:
        text = raw
        enc = 'utf-8'

    # 去掉 BOM
    if text.startswith('\ufeff'):
        text = text[1:]

    # 判定分隔符
    delim = delimiter or _detect_delimiter(text)

    # 逐行解析
    try:
        lines = text.splitlines()
        reader = csv_module.reader(lines, delimiter=delim)
        rows = [r for r in reader]
    except Exception:
        return None

    if not rows:
        return pd.DataFrame()

    # 用眾數當基準欄位數
    col_counts = Counter(len(r) for r in rows)
    target_cols = col_counts.most_common(1)[0][0]
    if target_cols < 2:
        target_cols = max(len(r) for r in rows)

    # 補齊或截斷
    normalized = []
    for r in rows:
        if len(r) < target_cols:
            r = r + [''] * (target_cols - len(r))
        elif len(r) > target_cols:
            r = r[:target_cols]
        normalized.append(r)

    return pd.DataFrame(normalized)


def load_any_file(file):
    """
    讀取 .xlsx / .xls / .csv
    回傳：(DataFrame, error_message)
    """
    if file is None:
        return None, "沒有檔案"

    try:
        file_size = len(file.getvalue())
    except Exception:
        file_size = 0

    if file_size > SINGLE_FILE_LIMIT:
        return None, f"檔案過大（{format_bytes(file_size)}），建議小於 50MB"

    name = file.name.lower()

    # ---------- CSV ----------
    if name.endswith('.csv'):
        df = _read_csv_robust(file)
        if df is None:
            # 最後 fallback：pandas 預設
            file.seek(0)
            try:
                df = pd.read_csv(file, encoding='utf-8-sig', header=None,
                                 on_bad_lines='skip', engine='python')
            except Exception:
                return None, "CSV 讀取失敗，可能是編碼問題或檔案損毀"

        if df.empty:
            return None, "檔案內容為空"

        if len(df) > ROW_WARNING_LIMIT:
            return df, f"檔案超過 {ROW_WARNING_LIMIT:,} 列，建議分批處理"
        return df, None

    # ---------- Excel ----------
    if name.endswith(('.xlsx', '.xls')):
        try:
            file.seek(0)
            df = pd.read_excel(file, header=None,
                               engine='openpyxl' if name.endswith('.xlsx') else None)
            if df.empty:
                return None, "檔案內容為空"
            if len(df) > ROW_WARNING_LIMIT:
                return df, f"檔案超過 {ROW_WARNING_LIMIT:,} 列，建議分批處理"
            return df, None
        except Exception as e:
            err = str(e).lower()
            if 'password' in err or 'encrypted' in err:
                return None, "此檔案受密碼保護，無法讀取"
            if 'not a zip' in err or 'badzipfile' in err:
                return None, "檔案格式錯誤，可能已損毀或非 Excel 檔案"
            return None, f"Excel 讀取失敗：{e}"

    return None, "不支援的檔案格式，僅接受 .xlsx / .xls / .csv"
