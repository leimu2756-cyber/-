"""智慧資料清理引擎"""
import re
import pandas as pd
import numpy as np

from utils import (
    to_halfwidth, flatten_newlines, convert_minguo_to_western,
    clean_currency_value, is_summary_row, is_non_data_row,
    parse_chinese_number, has_chinese_number, strip_unit_suffix,
    normalize_phone, is_phone_like, standardize_columns,
    EXCEL_ERRORS, NON_DATA_KEYWORDS, SUMMARY_KEYWORDS,
    CN_MONEY_INDICATORS,
)


def explain_invalid_date(value):
    """解釋為什麼一個日期無效"""
    if value is None or pd.isna(value):
        return "空值"
    s = str(value).strip()
    s = s.replace('（无效日期）', '').replace('（無效日期）', '').strip()

    m = re.match(r'^(\d{2,4})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
    if not m:
        m = re.match(r'^(\d{2,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
    if not m:
        return "無法識別的日期格式"

    try:
        y_raw, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    except Exception:
        return "無法解析日期"

    y = y_raw + 1911 if y_raw < 200 else y_raw

    if not (1 <= mo <= 12):
        return f"{mo} 月不存在"

    if not (1 <= d <= 31):
        return f"每月最多 31 天"

    month_days = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
                  7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    if (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0):
        month_days[2] = 29

    if d > month_days[mo]:
        return f"{mo} 月沒有 {d} 號"

    return "日期不存在"


class SmartCleaner:

    PATTERNS = {
        'email':     re.compile(r'^[\w\.\-\+]+@[\w\.\-]+\.\w+$'),
        'mobile_tw': re.compile(r'^09\d{8}$'),
        'phone_tw':  re.compile(r'^0\d{1,2}\-?\d{6,8}$'),
        'id_tw':     re.compile(r'^[A-Z][12]\d{8}$'),
        'tax_id_tw': re.compile(r'^\d{8}$'),
        'date_str':  re.compile(r'^(\d{2,4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})$'),
        'url':       re.compile(r'^https?://'),
        'currency':  re.compile(r'^[\sNT\$,\.\(\)\d\-]+$'),
    }

    TYPE_LABELS = {
        'email': '📧 Email', 'mobile_tw': '📱 手機號碼', 'phone_tw': '☎️ 市話',
        'id_tw': '🆔 身分證號', 'tax_id_tw': '🏢 統一編號', 'date_str': '📅 日期（文字）',
        'url': '🔗 網址', 'currency': '💰 金額', 'number': '🔢 數值',
        'date': '📅 日期', 'text': '📝 文字', 'empty': '⬜ 空欄位',
        'phone': '📞 電話',
    }

    @staticmethod
    def _match_ratio(series, pattern):
        s = series.dropna().astype(str).str.strip()
        if len(s) == 0:
            return 0.0
        try:
            return s.str.match(pattern).sum() / len(s)
        except Exception:
            return 0.0

    @classmethod
    def detect_column_type(cls, series):
        s = series.dropna()
        if len(s) == 0:
            return 'empty'
        s_str = s.astype(str).str.strip()
        if len(s_str) == 0:
            return 'empty'

        try:
            phone_count = s_str.apply(is_phone_like).sum()
            if phone_count / len(s_str) >= 0.6:
                return 'phone'
        except Exception:
            pass

        try:
            cn_count = s_str.apply(has_chinese_number).sum()
            if cn_count / len(s_str) >= 0.3:
                parseable = 0
                for v in s_str:
                    if has_chinese_number(v):
                        if parse_chinese_number(v) is not None:
                            parseable += 1
                    else:
                        try:
                            float(v)
                            parseable += 1
                        except ValueError:
                            pass
                if parseable / len(s_str) >= 0.6:
                    return 'number'
        except Exception:
            pass

        try:
            cn_money = s_str.apply(
                lambda x: any(ind in x for ind in CN_MONEY_INDICATORS)
            ).sum()
            if cn_money / len(s_str) >= 0.5:
                return 'currency'
        except Exception:
            pass

        try:
            currency_like = s_str.str.match(r'^[\sNT\$,\.\(\)\d\-]+$').sum()
            if currency_like / len(s_str) >= 0.4:
                pure_number = s_str.str.match(r'^-?\d+(\.\d+)?$').sum()
                if pure_number / len(s_str) < 0.9:
                    return 'currency'
        except Exception:
            pass

        try:
            scores = {n: cls._match_ratio(series, p) for n, p in cls.PATTERNS.items()}
            best, score = max(scores.items(), key=lambda x: x[1])
            if score >= 0.7:
                return best
        except Exception:
            pass

        try:
            pd.to_numeric(s)
            return 'number'
        except (ValueError, TypeError):
            pass

        try:
            parsed = pd.to_datetime(s, errors='coerce')
            if parsed.notna().sum() >= len(s) * 0.4:
                return 'date'
            invalid_date_count = s_str.str.contains(
                '（无效日期）|（無效日期）', regex=True, na=False
            ).sum()
            if invalid_date_count / len(s_str) >= 0.3:
                return 'date'
        except (ValueError, TypeError):
            pass

        try:
            date_like = s_str.str.match(
                r'^(\d{2,4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{2,4}年\d{1,2}月\d{1,2}日?)$'
            ).sum()
            if date_like / len(s_str) >= 0.4:
                return 'date_str'
        except Exception:
            pass

        return 'text'

    @classmethod
    def analyze_dataframe(cls, df):
        report = []
        for col in df.columns:
            try:
                col_type = cls.detect_column_type(df[col])
            except Exception:
                col_type = 'text'
            missing = int(df[col].isna().sum())
            unique = int(df[col].nunique(dropna=True))
            sample = df[col].dropna()
            sample_str = str(sample.iloc[0])[:40] if len(sample) > 0 else '（無資料）'
            report.append({
                '欄位名稱': col,
                'AI 識別類型': cls.TYPE_LABELS.get(col_type, col_type),
                '缺失值': missing,
                '缺失比例': f"{missing / max(len(df), 1) * 100:.1f}%",
                '唯一值數': unique,
                '範例資料': sample_str,
                '_raw_type': col_type,
            })
        return pd.DataFrame(report)

    @classmethod
    def clean_dataframe(cls, df, options=None):
        options = options or {}
        df_clean = df.copy().reset_index(drop=True)
        actions = []
        stats = {
            'rows_removed_non_data': 0,
            'rows_removed_summary': 0,
            'excel_errors_fixed': 0,
            'cells_halfwidth': 0,
            'cells_newline': 0,
            'dates_fixed': 0,
            'invalid_dates': [],
            'currency_fixed': 0,
            'chinese_numbers_fixed': 0,
            'unit_suffix_fixed': 0,
            'phones_fixed': 0,
            'emails_fixed': 0,
            'columns_cleaned': 0,
            'columns_standardized': 0,
            'duplicates_flagged': 0,
            'duplicates_records': [],
        }

        # 1. 非資料行
        if options.get('remove_non_data_rows', True):
            try:
                mask = df_clean.apply(is_non_data_row, axis=1)
                removed = int(mask.sum())
                if removed > 0:
                    df_clean = df_clean[~mask].reset_index(drop=True)
                    stats['rows_removed_non_data'] = removed
                    actions.append(f"✅ 移除 {removed} 行非資料列")
            except Exception:
                pass

        # 2. Excel 錯誤值
        if options.get('clean_excel_errors', True):
            total = 0
            try:
                for col in df_clean.columns:
                    for idx in df_clean.index:
                        v = df_clean.at[idx, col]
                        if pd.notna(v) and str(v).strip() in EXCEL_ERRORS:
                            df_clean.at[idx, col] = np.nan
                            total += 1
            except Exception:
                pass
            if total > 0:
                stats['excel_errors_fixed'] = total
                actions.append(f"✅ 清理 {total} 個 Excel 錯誤值")

        # 3. 全形 → 半形
        if options.get('normalize_width', True):
            cells = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    orig = df_clean[col].astype(str)
                    conv = orig.apply(to_halfwidth)
                    changed = (orig != conv).sum()
                    if changed > 0:
                        df_clean[col] = conv
                        cells += int(changed)
            except Exception:
                pass
            if cells > 0:
                stats['cells_halfwidth'] = cells
                actions.append(f"✅ 轉換 {cells} 個全形字元為半形")

        # 4. 換行
        if options.get('flatten_newlines', True):
            cells = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    orig = df_clean[col].astype(str)
                    conv = orig.apply(flatten_newlines)
                    changed = (orig != conv).sum()
                    if changed > 0:
                        df_clean[col] = conv
                        cells += int(changed)
            except Exception:
                pass
            if cells > 0:
                stats['cells_newline'] = cells
                actions.append(f"✅ 處理 {cells} 個換行符號")

        # ==========================================================
        # 5. 疑似重複標記（只標記，絕不刪除）
        # ==========================================================
        if options.get('flag_duplicates', True):
            try:
                dup_cols = options.get('duplicate_keys', [])
                if not dup_cols:
                    # 用所有欄位（排除來源檔案與疑似重複本身）
                    dup_cols = [
                        c for c in df_clean.columns
                        if c not in ('來源檔案', '疑似重複')
                    ]

                if dup_cols and len(df_clean) > 0:
                    dup_mask = df_clean.duplicated(subset=dup_cols, keep=False)
                    df_clean['疑似重複'] = dup_mask.apply(
                        lambda x: '是' if x else '否'
                    )
                    dup_count = int(dup_mask.sum())
                    stats['duplicates_flagged'] = dup_count

                    if dup_count > 0:
                        # 收集重複群組，供異常清單用
                        dup_indices = df_clean[dup_mask].index.tolist()
                        dup_records = []
                        for idx in dup_indices:
                            try:
                                this_row = df_clean.loc[idx, dup_cols]
                                matches = []
                                for other_idx in dup_indices:
                                    if other_idx == idx:
                                        continue
                                    if df_clean.loc[other_idx, dup_cols].equals(this_row):
                                        matches.append(int(other_idx) + 1)
                                if matches:
                                    dup_records.append({
                                        'row_index': int(idx) + 1,
                                        'matches': matches,
                                    })
                            except Exception:
                                pass
                        stats['duplicates_records'] = dup_records
                        actions.append(
                            f"⚠️ 發現 {dup_count} 筆疑似重複（僅標記，未刪除）"
                        )
                    else:
                        actions.append("✅ 未發現重複資料")
            except Exception as e:
                actions.append(f"⚠️ 重複偵測失敗：{e}")

        # 6. 欄位名稱清理
        if options.get('clean_columns', True):
            try:
                new_cols = [str(c).strip() for c in df_clean.columns]
                if list(df_clean.columns) != new_cols:
                    df_clean.columns = new_cols
                    actions.append("✅ 清理欄位名稱頭尾空白")
            except Exception:
                pass

        # 6-2. 欄位名稱標準化
        if options.get('standardize_columns', True):
            try:
                before_cols = list(df_clean.columns)
                df_clean = standardize_columns(df_clean, enabled=True)
                after_cols = list(df_clean.columns)
                changed = sum(1 for a, b in zip(before_cols, after_cols) if a != b)
                if changed > 0:
                    stats['columns_standardized'] = changed
                    renamed = [
                        f"「{a}」→「{b}」"
                        for a, b in zip(before_cols, after_cols) if a != b
                    ]
                    actions.append(
                        f"✅ 標準化 {changed} 個欄位名稱：" + "、".join(renamed)
                    )
            except Exception as e:
                actions.append(f"⚠️ 欄位名稱標準化失敗：{e}")

        # 7. 文字 trim（電話欄位保持字串）
        if options.get('trim_strings', True):
            touched = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    is_phone_col = False
                    try:
                        sample = df_clean[col].dropna().astype(str).head(20)
                        if len(sample) > 0:
                            phone_count = sample.apply(is_phone_like).sum()
                            if phone_count / len(sample) >= 0.5:
                                is_phone_col = True
                    except Exception:
                        pass

                    if is_phone_col:
                        df_clean[col] = df_clean[col].apply(
                            lambda x: normalize_phone(x) if pd.notna(x) else x
                        )
                        stats['phones_fixed'] += 1
                        actions.append(f"✅ 標準化「{col}」電話格式")
                    else:
                        df_clean[col] = (
                            df_clean[col].astype(str).str.strip()
                            .replace({'nan': np.nan, 'None': np.nan, '': np.nan})
                        )
                    touched += 1
            except Exception:
                pass
            if touched:
                stats['columns_cleaned'] = touched

        # 8. 日期清理
        if options.get('normalize_date', True):
            fixed = 0
            invalid_date_records = []
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        ctype = 'text'

                    s_str = df_clean[col].dropna().astype(str).str.strip()
                    is_date_col = ctype in ('date', 'date_str')

                    if not is_date_col and len(s_str) > 0:
                        try:
                            date_like = s_str.str.match(
                                r'^(\d{2,4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{2,4}年\d{1,2}月\d{1,2}日?)$'
                            ).sum()
                            if date_like / len(s_str) >= 0.3:
                                is_date_col = True
                        except Exception:
                            pass

                    if not is_date_col:
                        continue

                    orig = df_clean[col].tolist()
                    conv = []
                    for idx, v in enumerate(orig):
                        if pd.isna(v) or str(v).strip() == '':
                            conv.append(v)
                            continue

                        s = str(v).strip()
                        if '（无效日期）' in s or '（無效日期）' in s:
                            conv.append(v)
                            continue

                        result = convert_minguo_to_western(v)
                        result_str = str(result)

                        if '（无效日期）' in result_str or '（無效日期）' in result_str:
                            reason = explain_invalid_date(s)
                            invalid_date_records.append({
                                'column': col,
                                'row_index': idx + 1,
                                'raw_value': s,
                                'marked_value': result_str,
                                'reason': reason,
                            })
                            conv.append(result)
                        else:
                            conv.append(result)
                            if str(v) != result_str:
                                fixed += 1

                    df_clean[col] = conv
            except Exception:
                pass

            if fixed > 0:
                stats['dates_fixed'] = fixed
                actions.append(f"✅ 轉換 {fixed} 個日期格式")

            if invalid_date_records:
                stats['invalid_dates'] = invalid_date_records
                actions.append(
                    f"⚠️ 發現 {len(invalid_date_records)} 筆無效日期（已保留原始值）"
                )

        # 8-2. 中文數字轉換
        if options.get('normalize_chinese_number', True):
            cn_fixed = 0
            try:
                for col in df_clean.columns:
                    col_has_cn = False
                    for v in df_clean[col].dropna().astype(str):
                        if has_chinese_number(v):
                            col_has_cn = True
                            break
                    if not col_has_cn:
                        continue

                    orig = df_clean[col].tolist()
                    conv = []
                    for v in orig:
                        if pd.isna(v):
                            conv.append(v)
                            continue
                        s = str(v).strip()
                        if has_chinese_number(s):
                            parsed = parse_chinese_number(s)
                            if parsed is not None:
                                conv.append(parsed)
                                cn_fixed += 1
                                continue
                        conv.append(v)
                    df_clean[col] = conv
            except Exception:
                pass
            if cn_fixed > 0:
                stats['chinese_numbers_fixed'] = cn_fixed
                actions.append(f"✅ 轉換 {cn_fixed} 個中文數字")

        # 8-3. 單位尾綴移除
        if options.get('strip_units', True):
            unit_fixed = 0
            try:
                for col in df_clean.columns:
                    orig = df_clean[col].tolist()
                    conv = []
                    for v in orig:
                        if pd.isna(v):
                            conv.append(v)
                            continue
                        s = str(v).strip()
                        new_v = strip_unit_suffix(s)
                        if str(new_v) != s:
                            unit_fixed += 1
                        conv.append(new_v)
                    df_clean[col] = conv
            except Exception:
                pass
            if unit_fixed > 0:
                stats['unit_suffix_fixed'] = unit_fixed
                actions.append(f"✅ 移除 {unit_fixed} 個單位尾綴")

        # 9. 貨幣
        if options.get('clean_currency', True):
            fixed = 0
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype == 'currency':
                        orig = df_clean[col].tolist()
                        conv = [clean_currency_value(v) for v in orig]
                        changed = sum(1 for o, n in zip(orig, conv) if str(o) != str(n))
                        df_clean[col] = conv
                        fixed += changed
            except Exception:
                pass
            if fixed > 0:
                stats['currency_fixed'] = fixed
                actions.append(f"✅ 清理 {fixed} 個貨幣 / 中文數字")

        # 10. Email
        if options.get('normalize_email', True):
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype == 'email':
                        df_clean[col] = df_clean[col].astype(str).str.lower()
                        stats['emails_fixed'] += 1
                        actions.append(f"✅ 「{col}」Email 轉小寫")
            except Exception:
                pass

        # 12. 填補空白
        if options.get('fill_na'):
            fill_value = options.get('fill_value', '')
            df_clean = df_clean.fillna(fill_value)
            actions.append(f"✅ 空白值填補為「{fill_value}」")

        # 13. 彙總列
        summary_action = options.get('summary_row_action', 'keep')
        summary_df = None
        total_check = []
        try:
            summary_mask = df_clean.apply(is_summary_row, axis=1)
            summary_indices = list(df_clean[summary_mask].index)
            if summary_indices:
                total_check = cls._validate_totals(df_clean, summary_indices)
                if summary_action != 'keep':
                    summary_df = df_clean.loc[summary_indices].copy()
                    df_clean = df_clean.drop(index=summary_indices).reset_index(drop=True)
                    stats['rows_removed_summary'] = len(summary_indices)
                    if summary_action == 'remove':
                        actions.append(f"✅ 移除 {len(summary_indices)} 行彙總列")
                    else:
                        actions.append(f"✅ 分離 {len(summary_indices)} 行彙總列")
        except Exception:
            pass

        return df_clean, actions, stats, summary_df, total_check

    @staticmethod
    def _validate_totals(df, summary_indices):
        results = []
        detail = df.drop(index=summary_indices, errors='ignore')
        for col in df.columns:
            summary_vals = []
            for idx in summary_indices:
                try:
                    v = df.at[idx, col]
                except Exception:
                    continue
                if pd.isna(v):
                    continue
                try:
                    s = str(v).strip()
                    for token in ['NT$', 'NT', '$', ',', ' ', '元', '　']:
                        s = s.replace(token, '')
                    summary_vals.append(float(s))
                except (ValueError, TypeError):
                    continue
            if not summary_vals:
                continue
            detail_nums = pd.to_numeric(detail[col], errors='coerce').dropna()
            if len(detail_nums) == 0:
                continue
            calculated = float(detail_nums.sum())
            summary_value = float(sum(summary_vals))
            diff = round(summary_value - calculated, 2)
            if abs(diff) > 0.01:
                results.append({
                    'column': col,
                    'summary_value': summary_value,
                    'calculated_value': round(calculated, 2),
                    'difference': diff,
                })
        return results

    @classmethod
    def detect_anomalies(cls, df, source_name=''):
        anomalies = []

        # 1. 無效日期
        for col in df.columns:
            try:
                s = df[col].dropna().astype(str)
                invalid_mask = s.str.contains(
                    '（无效日期）|（無效日期）', regex=True, na=False
                )
                if invalid_mask.sum() > 0:
                    for idx in s[invalid_mask].index:
                        v = str(s[idx])
                        raw = v.replace('（无效日期）', '').replace('（無效日期）', '').strip()
                        reason = explain_invalid_date(raw)
                        try:
                            display_row = int(idx) + 1
                        except Exception:
                            display_row = str(idx)
                        anomalies.append({
                            '来源档案': source_name,
                            '列号': display_row,
                            '问题类型': '无效日期',
                            '说明': f"{raw} {reason}",
                            '建议': '请确认正确日期',
                        })
            except Exception:
                pass

        # 2. 疑似重複
        if '疑似重複' in df.columns:
            try:
                dup_mask = df['疑似重複'].astype(str).str.strip() == '是'
                if dup_mask.sum() > 0:
                    key_cols = [
                        c for c in df.columns
                        if c not in ('疑似重複', '來源檔案')
                    ]
                    dup_indices = df[dup_mask].index.tolist()
                    for idx in dup_indices:
                        try:
                            this_row = df.loc[idx, key_cols]
                            matches = []
                            for other_idx in dup_indices:
                                if other_idx == idx:
                                    continue
                                if df.loc[other_idx, key_cols].equals(this_row):
                                    matches.append(int(other_idx) + 1)
                            if matches:
                                match_str = '、'.join(
                                    f"第 {o} 行" for o in matches[:3]
                                )
                                if len(matches) > 3:
                                    match_str += " 等"
                                anomalies.append({
                                    '来源档案': source_name,
                                    '列号': int(idx) + 1,
                                    '问题类型': '疑似重複',
                                    '说明': f'与 {match_str} 资料相似，请确认是否为重复输入',
                                    '建议': '确认无误后可保留，或手动删除',
                                })
                        except Exception:
                            pass
            except Exception:
                pass

        # 3. 數值離群值 / 負數 / 非數值
        for col in df.columns:
            try:
                ctype = cls.detect_column_type(df[col])
            except Exception:
                continue

            if ctype == 'number':
                try:
                    s = pd.to_numeric(df[col], errors='coerce').dropna()
                    if len(s) > 10:
                        q1, q3 = s.quantile(0.25), s.quantile(0.75)
                        iqr = q3 - q1
                        if iqr > 0:
                            lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
                            outliers = s[(s < lo) | (s > hi)]
                            if len(outliers) > 0:
                                anomalies.append({
                                    '来源档案': source_name,
                                    '列号': '-',
                                    '问题类型': '数值离群值',
                                    '说明': f'欄位「{col}」有 {len(outliers)} 筆超出 [{lo:.2f}, {hi:.2f}]',
                                    '建议': '请确认数值是否正确',
                                })
                except Exception:
                    pass

            col_lower = str(col).lower()

            if any(kw in col_lower for kw in ['數量', '数量', 'qty', 'quantity', '個數', '个数']):
                try:
                    s = pd.to_numeric(df[col], errors='coerce').dropna()
                    neg = s[s < 0]
                    if len(neg) > 0:
                        anomalies.append({
                            '来源档案': source_name,
                            '列号': '-',
                            '问题类型': '负数数量',
                            '说明': f'欄位「{col}」有 {len(neg)} 筆負值',
                            '建议': '请确认数量是否正确',
                        })
                except Exception:
                    pass

            if any(kw in col_lower for kw in ['價格', '价格', '單價', '单价',
                                              '金額', '金额', '數量', '数量']):
                try:
                    s = df[col].dropna().astype(str)
                    weird = s[s.str.match(r'^[a-zA-Z\u4e00-\u9fa5]{1,10}$')]
                    if len(weird) > 0:
                        anomalies.append({
                            '来源档案': source_name,
                            '列号': '-',
                            '问题类型': '非数值内容',
                            '说明': f'欄位「{col}」有 {len(weird)} 筆文字，例如「{weird.iloc[0]}」',
                            '建议': '请确认内容是否正确',
                        })
                except Exception:
                    pass

        return anomalies

    @classmethod
    def quality_score(cls, df):
        if len(df) == 0 or len(df.columns) == 0:
            return 0
        try:
            total_cells = len(df) * len(df.columns)
            missing = int(df.isna().sum().sum())
            completeness = 1 - (missing / total_cells)

            scores = []
            for col in df.columns:
                try:
                    ctype = cls.detect_column_type(df[col])
                    if ctype in cls.PATTERNS:
                        scores.append(cls._match_ratio(df[col], cls.PATTERNS[ctype]))
                except Exception:
                    pass
            consistency = np.mean(scores) if scores else 1.0
            dup_ratio = 1 - (df.duplicated().sum() / len(df))
            score = completeness * 50 + consistency * 30 + dup_ratio * 20
            return round(score, 1)
        except Exception:
            return 0
