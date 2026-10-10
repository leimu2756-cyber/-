"""報告產生模組"""
import pandas as pd


def _format_num(v):
    """整數就顯示整數，避免 4385.0"""
    try:
        if pd.isna(v):
            return v
        if isinstance(v, float) and v == int(v):
            return int(v)
        return v
    except Exception:
        return v


def build_clean_report(stats, total_check=None, template_info=None):
    """建立清理報告 DataFrame（依模式顯示不同項目）"""
    invalid_dates = stats.get('invalid_dates', [])
    dup_mode = stats.get('duplicate_mode', 'mark')

    if dup_mode == 'drop':
        dup_label = "自動去重合併"
        dup_count = stats.get('duplicates_dropped', 0)
    else:
        dup_label = "發現疑似重複"
        dup_count = stats.get('duplicates_flagged', 0)

    rows = [
        ("移除非資料列", stats.get('rows_removed_non_data', 0), "列"),
        (dup_label, dup_count, "列"),
        ("移除彙總列", stats.get('rows_removed_summary', 0), "列"),
        ("Excel 錯誤值清理", stats.get('excel_errors_fixed', 0), "個"),
        ("全形轉半形", stats.get('cells_halfwidth', 0), "格"),
        ("換行符號處理", stats.get('cells_newline', 0), "格"),
        ("日期格式轉換", stats.get('dates_fixed', 0), "筆"),
        ("發現無效日期", len(invalid_dates), "筆"),
        ("貨幣 / 中文數字清理", stats.get('currency_fixed', 0), "筆"),
        ("中文數字轉換", stats.get('chinese_numbers_fixed', 0), "筆"),
        ("單位尾綴移除", stats.get('unit_suffix_fixed', 0), "筆"),
        ("欄位名稱標準化", stats.get('columns_standardized', 0), "個"),
    ]
    df = pd.DataFrame(rows, columns=["項目", "數量", "單位"])
    df = df[df["數量"] > 0]
    return df


def build_summary_rows(df_clean, total_check):
    """
    建立彙總列（附加在明細下方）
    差異 = 重算總計 − 原始總計
    """
    if not total_check or df_clean is None or len(df_clean.columns) == 0:
        return None

    cols = list(df_clean.columns)
    empty = {c: '' for c in cols}

    # 標籤欄位優先順序（產品、商品優先於備註）
    label_col = None
    for candidate in ['項目', '項目名稱', '品項', '產品', '產品名稱',
                      '商品', '商品名稱', '名稱', '科目', '費用',
                      '類別', '分類', '說明', '備註']:
        if candidate in cols:
            label_col = candidate
            break
    if label_col is None:
        label_col = cols[0]

    rows = []
    # 分隔列
    rows.append(empty.copy())

    multi = len(total_check) > 1

    for item in total_check:
        col_name = item.get('column', '')
        original = item.get('summary_value', 0)
        recalc = item.get('calculated_value', 0)
        # 差異 = 重算 − 原始
        diff = round(recalc - original, 2)

        suffix = f'（{col_name}）' if multi else ''

        # 原始總計
        r = empty.copy()
        r[label_col] = f'原始總計{suffix}'
        if col_name in cols:
            r[col_name] = _format_num(original)
        rows.append(r)

        # 重算總計
        r = empty.copy()
        r[label_col] = f'重算總計{suffix}'
        if col_name in cols:
            r[col_name] = _format_num(recalc)
        rows.append(r)

        # 差異
        r = empty.copy()
        r[label_col] = f'差異{suffix}'
        if col_name in cols:
            if diff > 0:
                r[col_name] = f'+{_format_num(diff)}'
            elif diff < 0:
                r[col_name] = str(_format_num(diff))
            else:
                r[col_name] = '0'
        rows.append(r)

    return pd.DataFrame(rows, columns=cols)


def build_total_summary_table(total_check):
    """總計摘要表（差異 = 重算 − 原始）"""
    if not total_check:
        return pd.DataFrame()
    rows = []
    for item in total_check:
        original = item.get('summary_value', 0)
        recalc = item.get('calculated_value', 0)
        diff = round(recalc - original, 2)
        rows.append({
            '欄位': item.get('column', ''),
            '原始總計': _format_num(original),
            '重算總計': _format_num(recalc),
            '差異': f'+{_format_num(diff)}' if diff > 0 else str(_format_num(diff)),
        })
    return pd.DataFrame(rows)


def build_invalid_date_table(invalid_dates):
    if not invalid_dates:
        return pd.DataFrame()
    rows = []
    for r in invalid_dates:
        rows.append({
            '欄位': r.get('column', ''),
            '列號': r.get('row_index', ''),
            '原始值': r.get('raw_value', ''),
            '標記後': r.get('marked_value', ''),
            '原因': r.get('reason', ''),
        })
    return pd.DataFrame(rows)


def build_duplicate_table(dup_records):
    if not dup_records:
        return pd.DataFrame()
    rows = []
    for r in dup_records:
        matches = r.get('matches', [])
        match_str = '、'.join(f"第 {m} 行" for m in matches[:5])
        if len(matches) > 5:
            match_str += " 等"
        rows.append({
            '列號': r.get('row_index', ''),
            '與哪些行相似': match_str,
        })
    return pd.DataFrame(rows)


def build_anomaly_table(anomalies):
    if not anomalies:
        return pd.DataFrame()
    df = pd.DataFrame(anomalies)
    preferred_order = ['来源档案', '列号', '问题类型', '说明', '建议']
    existing = [c for c in preferred_order if c in df.columns]
    other = [c for c in df.columns if c not in preferred_order]
    return df[existing + other]


def build_total_check_table(total_check, calculated_total=None, original_total=None):
    """總計驗證報告（差異 = 重算 − 原始）"""
    rows = []
    for item in (total_check or []):
        original = item.get('summary_value', 0)
        recalc = item.get('calculated_value', 0)
        diff = round(recalc - original, 2)
        pct = abs(diff) / max(recalc, 1) * 100
        rows.append({
            '欄位': item.get('column', ''),
            '原始總計': _format_num(original),
            '重算總計': _format_num(recalc),
            '差異': f'+{_format_num(diff)}' if diff > 0 else str(_format_num(diff)),
            '差異百分比': f"{pct:.2f}%",
            '警示': '🔴 超過 5%' if pct > 5 else '🟡 需確認',
        })
    return pd.DataFrame(rows)
