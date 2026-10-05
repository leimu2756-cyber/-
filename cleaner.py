"""智慧資料清理引擎"""
import re
import pandas as pd
import numpy as np

from utils import (
    to_halfwidth, flatten_newlines, convert_minguo_to_western,
    clean_currency_value, validate_date, is_summary_row, is_non_data_row,
    parse_chinese_number, has_chinese_number,
    EXCEL_ERRORS, NON_DATA_KEYWORDS, SUMMARY_KEYWORDS,
    CN_MONEY_INDICATORS,
)


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

        # 中文數字 → 視為數字
        try:
            cn_count = s_str.apply(has_chinese_number).sum()
            if cn_count / len(s_str) >= 0.3:
                # 如果大部分含中文數字，且可解析為數字
                parseable = 0
                for v in s_str:
                    if has_chinese_number(v):
                        if parse_chinese_number(v) is not None:
                            parseable += 1
                    else:
                        # 純數字也算
                        try:
                            float(v)
                            parseable += 1
                        except ValueError:
                            pass
                if parseable / len(s_str) >= 0.6:
                    return 'number'
        except Exception:
            pass

        # 貨幣
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
            'rows_removed_duplicate': 0,
            'rows_removed_summary': 0,
            'excel_errors_fixed': 0,
            'cells_halfwidth': 0,
            'cells_newline': 0,
            'dates_fixed': 0,
            'currency_fixed': 0,
            'chinese_numbers_fixed': 0,
            'phones_fixed': 0,
            'emails_fixed': 0,
            'columns_cleaned': 0,
            'duplicates_flagged': 0,
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

        # 5. 去重
        if options.get('drop_duplicates', True):
            try:
                before = len(df_clean)
                df_clean = df_clean.drop_duplicates().reset_index(drop=True)
                removed = before - len(df_clean)
                if removed > 0:
                    stats['rows_removed_duplicate'] = removed
                    actions.append(f"✅ 移除 {removed} 筆完全重複的列")
            except Exception:
                pass

        # 6. 欄位名稱
        if options.get('clean_columns', True):
            try:
                new_cols = [str(c).strip() for c in df_clean.columns]
                if list(df_clean.columns) != new_cols:
                    df_clean.columns = new_cols
                    actions.append("✅ 清理欄位名稱頭尾空白")
            except Exception:
                pass

        # 7. 文字 trim
        if options.get('trim_strings', True):
            touched = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    df_clean[col] = (
                        df_clean[col].astype(str).str.strip()
                        .replace({'nan': np.nan, 'None': np.nan, '': np.nan})
                    )
                    touched += 1
            except Exception:
                pass
            if touched:
                stats['columns_cleaned'] = touched
                actions.append(f"✅ 清理 {touched} 個文字欄位頭尾空白")

        # 8. 日期
        if options.get('normalize_date', True):
            fixed = 0
            try:
                for col in df_clean.columns:
                    orig = df_clean[col].tolist()
                    conv = [convert_minguo_to_western(v) for v in orig]
                    changed = sum(1 for o, n in zip(orig, conv) if str(o) != str(n))
                    if changed > 0:
                        df_clean[col] = conv
                        fixed += changed
            except Exception:
                pass
            if fixed > 0:
                stats['dates_fixed'] = fixed
                actions.append(f"✅ 轉換 {fixed} 個日期格式")

        # 8-2. 中文數字轉換（新增：全欄掃描）
        if options.get('normalize_chinese_number', True):
            cn_fixed = 0
            try:
                for col in df_clean.columns:
                    # 檢查該欄是否有中文數字
                    col_has_cn = False
                    for v in df_clean[col].dropna().astype(str):
                        if has_chinese_number(v):
                            col_has_cn = True
                            break
                    if not col_has_cn:
                        continue

                    # 逐值轉換
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
                actions.append(f"✅ 轉換 {cn_fixed} 個中文數字為阿拉伯數字")

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

        # 10. 電話
        if options.get('normalize_phone', True):
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype in ('phone_tw', 'mobile_tw'):
                        df_clean[col] = df_clean[col].astype(str).str.replace(r'[-\s\(\)]', '', regex=True)
                        stats['phones_fixed'] += 1
                        actions.append(f"✅ 標準化「{col}」電話格式")
            except Exception:
                pass

        # 11. Email
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

        # 14. 重複標記
        if options.get('flag_duplicates', False):
            try:
                key_cols = options.get('duplicate_keys', [])
                if key_cols:
                    dup_mask = df_clean.duplicated(subset=key_cols, keep=False)
                    if '疑似重複' not in df_clean.columns:
                        df_clean['疑似重複'] = ''
                    df_clean.loc[dup_mask, '疑似重複'] = '是'
                    stats['duplicates_flagged'] = int(dup_mask.sum())
                    if stats['duplicates_flagged'] > 0:
                        actions.append(f"⚠️ 標記 {stats['duplicates_flagged']} 筆疑似重複")
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
    def detect_anomalies(cls, df):
        anomalies = []
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
                                anomalies.append({'欄位': col, '類型': '數值離群值',
                                                 '數量': len(outliers),
                                                 '說明': f'超出 [{lo:.2f}, {hi:.2f}]'})
                except Exception:
                    pass

            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['數量', 'qty', 'quantity']):
                try:
                    s = pd.to_numeric(df[col], errors='coerce').dropna()
                    neg = s[s < 0]
                    if len(neg) > 0:
                        anomalies.append({'欄位': col, '類型': '負數數量',
                                         '數量': len(neg), '說明': '數量欄位出現負值'})
                except Exception:
                    pass

            if any(kw in col_lower for kw in ['價格', '單價', '金額', '數量']):
                try:
                    s = df[col].dropna().astype(str)
                    weird = s[s.str.match(r'^[a-zA-Z\u4e00-\u9fa5]{1,10}$')]
                    if len(weird) > 0:
                        anomalies.append({'欄位': col, '類型': '非數值內容',
                                         '數量': len(weird), '說明': '金額/數量欄位出現文字'})
                except Exception:
                    pass

            try:
                s = df[col].dropna().astype(str)
                invalid = s[s.str.contains('無效日期', na=False)]
                if len(invalid) > 0:
                    anomalies.append({'欄位': col, '類型': '無效日期',
                                     '數量': len(invalid), '說明': '日期欄位存在不存在的日期'})
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
