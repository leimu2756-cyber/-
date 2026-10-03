"""
智慧資料清理引擎 (Smart Data Cleaner) v2
新增功能：
  1. 移除非資料行（###、===、系統警告、公司名稱...）
  2. 清理 Excel 錯誤值（#VALUE!、#N/A...）
  3. 民國年自動轉西元
  4. 貨幣 / 會計數字清理（NT$ 5,000 → 5000、(8) → -8）
  5. 無效日期偵測（13月、2月30日）
  6. 欄位合理性檢查（數量為負、金額為文字）
"""

import re
import pandas as pd
import numpy as np


class SmartCleaner:

    PATTERNS = {
        'email':       re.compile(r'^[\w\.\-\+]+@[\w\.\-]+\.\w+$'),
        'mobile_tw':   re.compile(r'^09\d{8}$'),
        'phone_tw':    re.compile(r'^0\d{1,2}\-?\d{6,8}$'),
        'id_tw':       re.compile(r'^[A-Z][12]\d{8}$'),
        'tax_id_tw':   re.compile(r'^\d{8}$'),
        'date_str':    re.compile(r'^(\d{4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})$'),
        'url':         re.compile(r'^https?://'),
        'currency':    re.compile(r'^[\$NT\$,\d\.]+$'),
    }

    TYPE_LABELS = {
        'email':      '📧 Email',
        'mobile_tw':  '📱 手機號碼',
        'phone_tw':   '☎️ 市話',
        'id_tw':      '🆔 身分證號',
        'tax_id_tw':  '🏢 統一編號',
        'date_str':   '📅 日期（文字）',
        'url':        '🔗 網址',
        'currency':   '💰 金額',
        'number':     '🔢 數值',
        'date':       '📅 日期',
        'text':       '📝 文字',
        'empty':      '⬜ 空欄位',
    }

    # 明顯不是資料的行關鍵字
    NON_DATA_KEYWORDS = [
        '###', '===', '---',
        '系統警告', '報表結束', '資料嚴重損毀',
        '公司名稱', '備註：', '備註:',
    ]

    # Excel 常見錯誤值
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
        return s.str.match(pattern).sum() / len(s)

    @staticmethod
    def _is_non_data_row(row):
        """判斷這一行是否為非資料行（標題裝飾、警告、結尾）"""
        row_str = ' '.join(str(v) for v in row.values if pd.notna(v))
        if not row_str.strip():
            return False  # 空白行由 drop_duplicates 處理，這裡不重複
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

        scores = {name: cls._match_ratio(series, pat)
                  for name, pat in cls.PATTERNS.items()}
        best_name, best_score = max(scores.items(), key=lambda x: x[1])
        if best_score >= 0.7:
            return best_name

        try:
            pd.to_numeric(s)
            return 'number'
        except (ValueError, TypeError):
            pass

        try:
            pd.to_datetime(s, errors='raise', format='mixed')
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
            col_type = cls.detect_column_type(df[col])
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
    # 民國年 / 日期處理
    # ==========================================================
    @staticmethod
    def _convert_minguo_to_western(value):
        """把民國年字串轉成西元日期字串（無法轉換則回傳原值）"""
        if pd.isna(value):
            return value

        s = str(value).strip()
        if s == '' or s.lower() == 'nan':
            return np.nan

        # 格式 1：民國115年5月25日
        m = re.match(r'^民國\s*(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return SmartCleaner._validate_date(y + 1911, mo, d)

        # 格式 2：115年5月25日
        m = re.match(r'^(\d{2,3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= y <= 200:  # 合理民國年範圍
                return SmartCleaner._validate_date(y + 1911, mo, d)

        # 格式 3：115/5/20 或 115-5-20（三位數年視為民國）
        m = re.match(r'^(\d{2,3})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= y <= 200:
                return SmartCleaner._validate_date(y + 1911, mo, d)

        return value

    @staticmethod
    def _validate_date(y, mo, d):
        """驗證日期是否合法，合法回傳 YYYY-MM-DD 字串，不合法回傳原值"""
        try:
            return pd.Timestamp(year=y, month=mo, day=d).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return f"{y}-{mo:02d}-{d:02d}（無效日期）"

    # ==========================================================
    # 貨幣 / 數字清理
    # ==========================================================
    @staticmethod
    def _clean_currency_value(value):
        """NT$ 5,000 → 5000， (8) → -8"""
        if pd.isna(value):
            return value
        s = str(value).strip()

        # 會計負數格式 (8) 或 (1,200)
        m = re.match(r'^\(([\d,\.]+)\)$', s)
        if m:
            try:
                return -float(m.group(1).replace(',', ''))
            except ValueError:
                return value

        # 移除貨幣符號、千分位
        cleaned = re.sub(r'[NT\$\s,元]', '', s)
        cleaned = cleaned.replace('NT', '').replace('$', '')
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
        df_clean = df.copy()
        actions = []

        # ---------------------------------------------------
        # 1. 移除非資料行
        # ---------------------------------------------------
        if options.get('remove_non_data_rows', True):
            mask = df_clean.apply(cls._is_non_data_row, axis=1)
            removed = int(mask.sum())
            if removed > 0:
                df_clean = df_clean[~mask].reset_index(drop=True)
                actions.append(f"✅ 移除 {removed} 行非資料列（警告 / 標題裝飾 / 結尾）")

        # ---------------------------------------------------
        # 2. 清理 Excel 錯誤值
        # ---------------------------------------------------
        if options.get('clean_excel_errors', True):
            total_fixed = 0
            for col in df_clean.columns:
                s = df_clean[col].astype(str).str.strip()
                mask = s.isin(cls.EXCEL_ERRORS)
                total_fixed += int(mask.sum())
                df_clean.loc[mask, col] = np.nan
            if total_fixed > 0:
                actions.append(f"✅ 清理 {total_fixed} 個 Excel 錯誤值（#VALUE! 等）")

        # ---------------------------------------------------
        # 3. 移除完全重複列
        # ---------------------------------------------------
        if options.get('drop_duplicates', True):
            before = len(df_clean)
            df_clean = df_clean.drop_duplicates()
            removed = before - len(df_clean)
            if removed > 0:
                actions.append(f"✅ 移除 {removed} 筆完全重複的列")

        # ---------------------------------------------------
        # 4. 清理欄位名稱
        # ---------------------------------------------------
        if options.get('clean_columns', True):
            new_cols = [str(c).strip() for c in df_clean.columns]
            if list(df_clean.columns) != new_cols:
                df_clean.columns = new_cols
                actions.append("✅ 清理欄位名稱的頭尾空白")

        # ---------------------------------------------------
        # 5. 文字欄位 trim
        # ---------------------------------------------------
        if options.get('trim_strings', True):
            touched = 0
            for col in df_clean.select_dtypes(include=['object']).columns:
                df_clean[col] = (
                    df_clean[col].astype(str)
                    .str.strip()
                    .replace({'nan': np.nan, 'None': np.nan, '': np.nan})
                )
                touched += 1
            if touched:
                actions.append(f"✅ 清理 {touched} 個文字欄位的頭尾空白")

        # ---------------------------------------------------
        # 6. 民國年轉西元 + 日期標準化 + 無效日期偵測
        # ---------------------------------------------------
        if options.get('normalize_date', True):
            date_fixed = 0
            invalid_dates = 0
            for col in df_clean.columns:
                ctype = cls.detect_column_type(df_clean[col])

                # 6-1 民國年轉換（先掃描字串欄位）
                if ctype in ('text', 'date_str', 'date'):
                    converted = df_clean[col].apply(cls._convert_minguo_to_western)
                    changed = (converted.astype(str) != df_clean[col].astype(str)).sum()
                    if changed > 0:
                        df_clean[col] = converted
                        date_fixed += changed
                        # 重新偵測類型
                        ctype = cls.detect_column_type(df_clean[col])

                # 6-2 標準化為 YYYY-MM-DD
                if ctype == 'date':
                    try:
                        parsed = pd.to_datetime(df_clean[col], errors='coerce')
                        invalid_mask = parsed.isna() & df_clean[col].notna()
                        invalid_dates += int(invalid_mask.sum())
                        df_clean[col] = parsed.dt.strftime('%Y-%m-%d')
                    except Exception:
                        pass

            if date_fixed > 0:
                actions.append(f"✅ 轉換 {date_fixed} 個民國年日期為西元")
            if invalid_dates > 0:
                actions.append(f"⚠️ 偵測到 {invalid_dates} 個無效日期，已標記為空白")

        # ---------------------------------------------------
        # 7. 貨幣 / 會計數字清理
        # ---------------------------------------------------
        if options.get('clean_currency', True):
            currency_fixed = 0
            for col in df_clean.columns:
                ctype = cls.detect_column_type(df_clean[col])
                if ctype == 'currency':
                    original = df_clean[col].copy()
                    df_clean[col] = df_clean[col].apply(cls._clean_currency_value)
                    changed = (original.astype(str) != df_clean[col].astype(str)).sum()
                    currency_fixed += changed
            if currency_fixed > 0:
                actions.append(f"✅ 清理 {currency_fixed} 個貨幣 / 會計格式數字")

        # ---------------------------------------------------
        # 8. 電話標準化
        # ---------------------------------------------------
        if options.get('normalize_phone', True):
            for col in df_clean.columns:
                ctype = cls.detect_column_type(df_clean[col])
                if ctype in ('phone_tw', 'mobile_tw'):
                    df_clean[col] = (df_clean[col].astype(str)
                                     .str.replace(r'[-\s\(\)]', '', regex=True))
                    actions.append(f"✅ 標準化「{col}」的電話格式")

        # ---------------------------------------------------
        # 9. Email 小寫
        # ---------------------------------------------------
        if options.get('normalize_email', True):
            for col in df_clean.columns:
                ctype = cls.detect_column_type(df_clean[col])
                if ctype == 'email':
                    df_clean[col] = df_clean[col].astype(str).str.lower()
                    actions.append(f"✅ 將「{col}」的 Email 轉為小寫")

        # ---------------------------------------------------
        # 10. 填補空白
        # ---------------------------------------------------
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
            ctype = cls.detect_column_type(df[col])

            # 數值離群值
            if ctype == 'number':
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

            # 格式混用
            if ctype in ('phone_tw', 'mobile_tw'):
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

            # 負數數量偵測
            col_lower = str(col).lower()
            if any(kw in col_lower for kw in ['數量', 'qty', 'quantity', '個數']):
                s = pd.to_numeric(df[col], errors='coerce').dropna()
                negatives = s[s < 0]
                if len(negatives) > 0:
                    anomalies.append({
                        '欄位': col,
                        '類型': '負數數量',
                        '數量': len(negatives),
                        '說明': '數量欄位出現負值，可能是輸入錯誤',
                    })

            # 文字卡在數字欄位
            if ctype == 'text':
                s = df[col].dropna().astype(str)
                weird = s[s.str.match(r'^[a-zA-Z]{1,5}$')]
                if len(weird) > 0 and any(kw in str(col).lower() for kw in ['價格', '單價', '金額', '數量']):
                    anomalies.append({
                        '欄位': col,
                        '類型': '非數值內容',
                        '數量': len(weird),
                        '說明': '金額 / 數量欄位出現純文字',
                    })

        return anomalies

    # ==========================================================
    # 品質評分
    # ==========================================================
    @classmethod
    def quality_score(cls, df):
        if len(df) == 0 or len(df.columns) == 0:
            return 0

        total_cells = len(df) * len(df.columns)
        missing_cells = int(df.isna().sum().sum())
        completeness = 1 - (missing_cells / total_cells)

        consistency_scores = []
        for col in df.columns:
            ctype = cls.detect_column_type(df[col])
            if ctype in cls.PATTERNS:
                consistency_scores.append(
                    cls._match_ratio(df[col], cls.PATTERNS[ctype])
                )
        consistency = np.mean(consistency_scores) if consistency_scores else 1.0

        dup_ratio = 1 - (df.duplicated().sum() / len(df))

        score = (completeness * 50) + (consistency * 30) + (dup_ratio * 20)
        return round(score, 1)
