"""
智慧資料清理引擎 (Smart Data Cleaner) v3
更新：
  1. 貨幣偵測放寬（容許空格、NT$、$、千分位、會計負號）
  2. 無效日期標準化（2026/02/30 → 2026-02-30（無效日期））
  3. 民國年轉西元（115年5月25日 → 2026-05-25）
  4. 非資料行移除（###、===、系統警告、公司名稱、備註）
  5. Excel 錯誤值清理（#VALUE!、#N/A、NaN）
  6. 貨幣 / 會計數字清理（NT$ 5,000 → 5000、(8) → -8）
  7. 異常偵測（負數數量、格式混用、離群值、非數值內容）
"""

import re
import pandas as pd
import numpy as np


class SmartCleaner:

    # ==========================================================
    # 正則表達式
    # ==========================================================
    PATTERNS = {
        'email':     re.compile(r'^[\w\.\-\+]+@[\w\.\-]+\.\w+$'),
        'mobile_tw': re.compile(r'^09\d{8}$'),
        'phone_tw':  re.compile(r'^0\d{1,2}\-?\d{6,8}$'),
        'id_tw':     re.compile(r'^[A-Z][12]\d{8}$'),
        'tax_id_tw': re.compile(r'^\d{8}$'),
        'date_str':  re.compile(r'^(\d{4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})$'),
        'url':       re.compile(r'^https?://'),
        # 放寬：容許 NT$、$、逗號、括號、負號、空格
        'currency':  re.compile(r'^[\sNT\$,\.\(\)\d\-]+$'),
    }

    TYPE_LABELS = {
        'email':     '📧 Email',
        'mobile_tw': '📱 手機號碼',
        'phone_tw':  '☎️ 市話',
        'id_tw':     '🆔 身分證號',
        'tax_id_tw': '🏢 統一編號',
        'date_str':  '📅 日期（文字）',
        'url':       '🔗 網址',
        'currency':  '💰 金額',
        'number':    '🔢 數值',
        'date':      '📅 日期',
        'text':      '📝 文字',
        'empty':     '⬜ 空欄位',
    }

    NON_DATA_KEYWORDS = [
        '###', '===', '---',
        '系統警告', '報表結束', '資料嚴重損毀',
        '公司名稱', '備註：', '備註:',
    ]

    EXCEL_ERRORS = [
        '#VALUE!', '#N/A', '#DIV/0!', '#REF!',
        '#NAME?', '#NULL!', '#NUM!', 'N/A', 'NULL',
    ]

    # ==========================================================
    # 內部工具
    # ==========================================================
    @staticmethod
    def _match_ratio(series, pattern):
        s = series.dropna().astype(str).str.strip()
        if len(s) == 0:
            return 0.0
        try:
            return s.str.match(pattern).sum() / len(s)
        except Exception:
            return 0.0

    @staticmethod
    def _is_non_data_row(row):
        """判斷是否為非資料行"""
        try:
            row_str = ' '.join(str(v) for v in row.values if pd.notna(v))
        except Exception:
            return False
        if not row_str.strip():
            return False
        for kw in SmartCleaner.NON_DATA_KEYWORDS:
            if kw in row_str:
                return True
        return False

    # ==========================================================
    # 欄位類型偵測
    # ==========================================================
    @classmethod
    def detect_column_type(cls, series):
        s = series.dropna()
        if len(s) == 0:
            return 'empty'

        s_str = s.astype(str).str.strip()
        if len(s_str) == 0:
            return 'empty'

        # 優先檢查：貨幣 / 數字混雜格式
        try:
            currency_like = s_str.str.match(r'^[\sNT\$,\.\(\)\d\-]+$').sum()
            if currency_like / len(s_str) >= 0.7:
                pure_number = s_str.str.match(r'^-?\d+(\.\d+)?$').sum()
                # 若純數字比例低於 90%，視為 currency
                if pure_number / len(s_str) < 0.9:
                    return 'currency'
        except Exception:
            pass

        # 一般 pattern 比對
        try:
            scores = {name: cls._match_ratio(series, pat)
                      for name, pat in cls.PATTERNS.items()}
            best_name, best_score = max(scores.items(), key=lambda x: x[1])
            if best_score >= 0.7:
                return best_name
        except Exception:
            pass

        # 數值
        try:
            pd.to_numeric(s)
            return 'number'
        except (ValueError, TypeError):
            pass

        # 日期
        try:
            parsed = pd.to_datetime(s, errors='coerce')
            if parsed.notna().sum() >= len(s) * 0.7:
                return 'date'
        except (ValueError, TypeError):
            pass

        return 'text'

    # ==========================================================
    # 分析報告
    # ==========================================================
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

    # ==========================================================
    # 日期處理
    # ==========================================================
    @staticmethod
    def _validate_date(y, mo, d):
        """驗證日期是否合法，合法回傳 YYYY-MM-DD，不合法回傳標記字串"""
        try:
            if not (1 <= mo <= 12):
                return f"{y}-{mo:02d}-{d:02d}（無效日期）"
            if not (1 <= d <= 31):
                return f"{y}-{mo:02d}-{d:02d}（無效日期）"
            ts = pd.Timestamp(year=y, month=mo, day=d)
            return ts.strftime('%Y-%m-%d')
        except Exception:
            return f"{y}-{mo:02d}-{d:02d}（無效日期）"

    @staticmethod
    def _convert_minguo_to_western(value):
        """民國年 → 西元日期字串"""
        if pd.isna(value):
            return value

        s = str(value).strip()
        if s == '' or s.lower() == 'nan':
            return np.nan

        # 民國115年5月25日
        m = re.match(r'^民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return SmartCleaner._validate_date(y + 1911, mo, d)

        # 115年5月25日
        m = re.match(r'^(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= y <= 200:
                return SmartCleaner._validate_date(y + 1911, mo, d)

        # 115/5/20 或 115-5-20（三位數年視為民國）
        m = re.match(r'^(\d{2,3})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= y <= 200:
                return SmartCleaner._validate_date(y + 1911, mo, d)

        # 已經是 4 位西元年：驗證是否為合法日期（抓 2026/02/30 這種）
        m = re.match(r'^(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return SmartCleaner._validate_date(y, mo, d)

        return value

    # ==========================================================
    # 貨幣清理
    # ==========================================================
    @staticmethod
    def _clean_currency_value(value):
        """NT$ 5,000 → 5000， (8) → -8"""
        if pd.isna(value):
            return value
        s = str(value).strip()
        if s == '' or s.lower() == 'nan':
            return np.nan

        # 會計負數 (8) 或 (1,200)
        m = re.match(r'^\(([\d,\.]+)\)$', s)
        if m:
            try:
                return -float(m.group(1).replace(',', ''))
            except ValueError:
                return value

        # 移除貨幣符號、千分位、空格、元
        cleaned = s
        for token in ['NT$', 'NT', 'nt$', 'nt', '$', ',', ' ', '元', '　']:
            cleaned = cleaned.replace(token, '')

        try:
            if cleaned == '' or cleaned == '-':
                return value
            return float(cleaned)
        except ValueError:
            return value

    # ==========================================================
    # 主清理函式
    # ==========================================================
    @classmethod
    def clean_dataframe(cls, df, options=None):
        options = options or {}
        df_clean = df.copy().reset_index(drop=True)
        actions = []

        # ---------- 1. 移除非資料行 ----------
        if options.get('remove_non_data_rows', True):
            try:
                mask = df_clean.apply(cls._is_non_data_row, axis=1)
                removed = int(mask.sum())
                if removed > 0:
                    df_clean = df_clean[~mask].reset_index(drop=True)
                    actions.append(f"✅ 移除 {removed} 行非資料列（警告 / 標題裝飾 / 結尾）")
            except Exception as e:
                actions.append(f"⚠️ 非資料行偵測失敗：{e}")

        # ---------- 2. 清理 Excel 錯誤值 ----------
        if options.get('clean_excel_errors', True):
            total_fixed = 0
            try:
                for col in df_clean.columns:
                    for idx in df_clean.index:
                        val = df_clean.at[idx, col]
                        if pd.notna(val) and str(val).strip() in cls.EXCEL_ERRORS:
                            df_clean.at[idx, col] = np.nan
                            total_fixed += 1
            except Exception:
                pass
            if total_fixed > 0:
                actions.append(f"✅ 清理 {total_fixed} 個 Excel 錯誤值（#VALUE! 等）")

        # ---------- 3. 去重 ----------
        if options.get('drop_duplicates', True):
            try:
                before = len(df_clean)
                df_clean = df_clean.drop_duplicates().reset_index(drop=True)
                removed = before - len(df_clean)
                if removed > 0:
                    actions.append(f"✅ 移除 {removed} 筆完全重複的列")
            except Exception:
                pass

        # ---------- 4. 欄位名稱清理 ----------
        if options.get('clean_columns', True):
            try:
                new_cols = [str(c).strip() for c in df_clean.columns]
                if list(df_clean.columns) != new_cols:
                    df_clean.columns = new_cols
                    actions.append("✅ 清理欄位名稱的頭尾空白")
            except Exception:
                pass

        # ---------- 5. 文字欄位 trim ----------
        if options.get('trim_strings', True):
            touched = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    df_clean[col] = (
                        df_clean[col].astype(str)
                        .str.strip()
                        .replace({'nan': np.nan, 'None': np.nan, '': np.nan})
                    )
                    touched += 1
            except Exception:
                pass
            if touched:
                actions.append(f"✅ 清理 {touched} 個文字欄位的頭尾空白")

        # ---------- 6. 民國年轉換 + 日期標準化 ----------
        if options.get('normalize_date', True):
            date_fixed = 0
            invalid_dates = 0
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue

                    # 6-1 民國年轉換（對文字或日期欄位）
                    if ctype in ('text', 'date_str', 'date'):
                        try:
                            original = df_clean[col].tolist()
                            converted = [
                                cls._convert_minguo_to_western(v)
                                for v in original
                            ]
                            changed = sum(
                                1 for o, n in zip(original, converted)
                                if str(o) != str(n)
                            )
                            if changed > 0:
                                df_clean[col] = converted
                                date_fixed += changed
                        except Exception:
                            pass

                    # 6-2 標準化為 YYYY-MM-DD（含無效日期標記）
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue

                    if ctype == 'date':
                        try:
                            original = df_clean[col].tolist()
                            new_vals = []
                            for v in original:
                                if pd.isna(v):
                                    new_vals.append(np.nan)
                                    continue
                                s = str(v).strip()
                                m = re.match(r'^(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
                                if m:
                                    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                                    result = cls._validate_date(y, mo, d)
                                    if '無效' in result:
                                        invalid_dates += 1
                                    new_vals.append(result)
                                else:
                                    new_vals.append(v)
                            df_clean[col] = new_vals
                        except Exception:
                            pass
            except Exception:
                pass

            if date_fixed > 0:
                actions.append(f"✅ 轉換 {date_fixed} 個民國年日期為西元")
            if invalid_dates > 0:
                actions.append(f"⚠️ 偵測到 {invalid_dates} 個無效日期，已標記")

        # ---------- 7. 貨幣清理 ----------
        if options.get('clean_currency', True):
            currency_fixed = 0
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype == 'currency':
                        try:
                            original = df_clean[col].tolist()
                            converted = [cls._clean_currency_value(v) for v in original]
                            changed = sum(
                                1 for o, n in zip(original, converted)
                                if str(o) != str(n)
                            )
                            df_clean[col] = converted
                            currency_fixed += changed
                        except Exception:
                            pass
            except Exception:
                pass
            if currency_fixed > 0:
                actions.append(f"✅ 清理 {currency_fixed} 個貨幣 / 會計格式數字")

        # ---------- 8. 電話標準化 ----------
        if options.get('normalize_phone', True):
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype in ('phone_tw', 'mobile_tw'):
                        df_clean[col] = (df_clean[col].astype(str)
                                         .str.replace(r'[-\s\(\)]', '', regex=True))
                        actions.append(f"✅ 標準化「{col}」的電話格式")
            except Exception:
                pass

        # ---------- 9. Email 小寫 ----------
        if options.get('normalize_email', True):
            try:
                for col in df_clean.columns:
                    try:
                        ctype = cls.detect_column_type(df_clean[col])
                    except Exception:
                        continue
                    if ctype == 'email':
                        df_clean[col] = df_clean[col].astype(str).str.lower()
                        actions.append(f"✅ 將「{col}」的 Email 轉為小寫")
            except Exception:
                pass

        # ---------- 10. 填補空白 ----------
        if options.get('fill_na'):
            fill_value = options.get('fill_value', '')
            df_clean = df_clean.fillna(fill_value)
            actions.append(f"✅ 將空白值填補為「{fill_value}」")

        return df_clean, actions

    # ==========================================================
    # 異常偵測
    # ==========================================================
    @classmethod
    def detect_anomalies(cls, df):
        anomalies = []

        for col in df.columns:
            try:
                ctype = cls.detect_column_type(df[col])
            except Exception:
                continue

            # 數值離群值
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
                                    '欄位': col,
                                    '類型': '數值離群值',
                                    '數量': len(outliers),
                                    '說明': f'超出 [{lo:.2f}, {hi:.2f}] 範圍',
                                })
                except Exception:
                    pass

            # 格式混用（手機 + 市話）
            if ctype in ('phone_tw', 'mobile_tw'):
                try:
                    s = df[col].dropna().astype(str)
                    has_mobile = s.str.match(r'^09\d{8}$').any()
                    has_landline = s.str.match(r'^0\d{1,2}\-?\d{6,8}$').any()
                    if has_mobile and has_landline:
                        anomalies.append({
                            '欄位': col,
                            '類型': '格式混用',
                            '數量': len(s),
                            '說明': '同一欄位包含手機與市話格式',
                        })
                except Exception:
                    pass

            # 負數數量
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['數量', 'qty', 'quantity', '個數']):
                try:
                    s = pd.to_numeric(df[col], errors='coerce').dropna()
                    negatives = s[s < 0]
                    if len(negatives) > 0:
                        anomalies.append({
                            '欄位': col,
                            '類型': '負數數量',
                            '數量': len(negatives),
                            '說明': '數量欄位出現負值，可能是輸入錯誤',
                        })
                except Exception:
                    pass

            # 金額欄位出現純文字
            if any(kw in col_lower for kw in ['價格', '單價', '金額', '數量']):
                try:
                    s = df[col].dropna().astype(str)
                    weird = s[s.str.match(r'^[a-zA-Z\u4e00-\u9fa5]{1,10}$')]
                    if len(weird) > 0:
                        anomalies.append({
                            '欄位': col,
                            '類型': '非數值內容',
                            '數量': len(weird),
                            '說明': '金額 / 數量欄位出現文字',
                        })
                except Exception:
                    pass

        return anomalies

    # ==========================================================
    # 品質評分
    # ==========================================================
    @classmethod
    def quality_score(cls, df):
        if len(df) == 0 or len(df.columns) == 0:
            return 0

        try:
            total_cells = len(df) * len(df.columns)
            missing_cells = int(df.isna().sum().sum())
            completeness = 1 - (missing_cells / total_cells)

            consistency_scores = []
            for col in df.columns:
                try:
                    ctype = cls.detect_column_type(df[col])
                    if ctype in cls.PATTERNS:
                        consistency_scores.append(
                            cls._match_ratio(df[col], cls.PATTERNS[ctype])
                        )
                except Exception:
                    pass
            consistency = np.mean(consistency_scores) if consistency_scores else 1.0

            dup_ratio = 1 - (df.duplicated().sum() / len(df))

            score = (completeness * 50) + (consistency * 30) + (dup_ratio * 20)
            return round(score, 1)
        except Exception:
            return 0
