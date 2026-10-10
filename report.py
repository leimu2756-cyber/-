"""報告產生模組"""
import pandas as pd


def build_clean_report(stats, total_check=None, template_info=None):
    """建立清理報告 DataFrame"""
    invalid_dates = stats.get('invalid_dates', [])
    rows = [
        ("移除非資料列", stats.get('rows_removed_non_data', 0), "列"),
        ("發現疑似重複", stats.get('duplicates_flagged', 0), "列"),
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


def build_invalid_date_table(invalid_dates):
    """建立無效日期明細表"""
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
    """建立疑似重複明細表"""
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
    """建立異常清單 DataFrame"""
    if not anomalies:
        return pd.DataFrame()
    df = pd.DataFrame(anomalies)
    preferred_order = ['来源档案', '列号', '问题类型', '说明', '建议']
    existing = [c for c in preferred_order if c in df.columns]
    other = [c for c in df.columns if c not in preferred_order]
    return df[existing + other]


def build_total_check_table(total_check, calculated_total=None, original_total=None):
    """建立總計驗證報告"""
    rows = []
    for item in (total_check or []):
        diff = item['difference']
        pct = abs(diff) / max(item['calculated_value'], 1) * 100
        rows.append({
            '欄位': item['column'],
            '明細加總': item['calculated_value'],
            '原始總計': item['summary_value'],
            '差額': diff,
            '差額百分比': f"{pct:.2f}%",
            '警示': '🔴 超過 5%' if pct > 5 else '🟡 需確認',
        })
    return pd.DataFrame(rows)
