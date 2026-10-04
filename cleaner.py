"""
智慧資料清理引擎 (Smart Data Cleaner) v7
更新：
  - 日期轉換不再依賴欄位類型判斷，直接對每一列嘗試轉換
"""

import re
import pandas as pd
import numpy as np


CN_NUM = {
    '零': 0, '〇': 0,
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9,
    '壹': 1, '貳': 2, '參': 3, '叁': 3, '肆': 4, '伍': 5,
    '陸': 6, '柒': 7, '捌': 8, '玖': 9,
}

CN_UNIT = {
    '拾': 10, '佰': 100, '仟': 1000,
    '十': 10, '百': 100, '千': 1000,
    '萬': 10000, '万': 10000,
    '億': 100000000, '亿': 100000000,
}

CN_SUFFIXES = ['元整', '元正', '圓整', '元', '整', '圓', '圆', '圆整']


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

    CN_MONEY_INDICATORS = [
        '壹', '貳', '參', '叁', '肆', '伍', '陸', '柒', '捌', '玖',
        '拾', '佰', '仟', '萬', '億', '元整',
    ]

    @staticmethod
    def parse_chinese_number(text):
        if text is None:
            return None
        s = str(text).strip()
        if s == '':
            return None

        for suf in CN_SUFFIXES:
            if s.endswith(suf):
                s = s[:-len(suf)].strip()
                break

        if s == '':
            return None

        try:
            return float(s)
        except ValueError:
            pass

        total = 0
        section = 0
        current = 0
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

    @staticmethod
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

    @staticmethod
    def flatten_newlines(value):
        if pd.isna(value):
            return value
        s = str(value)
        s = s.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
        s = re.sub(r'\s+', ' ', s)
        return s.strip()

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

        for kw in SmartCleaner.NON_DATA_KEYWORDS:
            if kw in row_str:
                return True

        return False

    @classmethod
    def detect_column_type(cls, series):
        s = series.dropna()
        if len(s) == 0:
            return 'empty'

        s_str = s.astype(str).str.strip()
        if len(s_str) == 0:
            return 'empty'

        # 中文數字金額
        try:
            cn_count = s_str.apply(
                lambda x: any(ind in x for ind in cls.CN_MONEY_INDICATORS)
            ).sum()
            if len(s_str) > 0 and cn_count / len(s_str) >= 0.5:
                return 'currency'
        except Exception:
            pass

        # 貨幣 / 數字混雜
        try:
            currency_like = s_str.str.match(r'^[\sNT\$,\.\(\)\d\-]+$').sum()
            if len(s_str) > 0 and currency_like / len(s_str) >= 0.4:
                pure_number = s_str.str.match(r'^-?\d+(\.\d+)?$').sum()
                if pure_number / len(s_str) < 0.9:
                    return 'currency'
        except Exception:
            pass

        # 一般 pattern
        try:
            scores = {name: cls._match_ratio(series, pat)
                      for name, pat in cls.PATTERNS.items()}
            best_name, best_score = max(scores.items(), key=lambda x: x[1])
            if best_score >= 0.7:
                return best_name
        except Exception:
            pass

        # 純數值
        try:
            pd.to_numeric(s)
            return 'number'
        except (ValueError, TypeError):
            pass

        # 日期（pandas 解析）
        try:
            parsed = pd.to_datetime(s, errors='coerce')
            if len(s) > 0 and parsed.notna().sum() >= len(s) * 0.4:
                return 'date'
        except (ValueError, TypeError):
            pass

        # 日期格式字串（含民國年、中文日期）
        try:
            date_like = s_str.str.match(
                r'^(\d{2,4}[\-/]\d{1,2}[\-/]\d{1,2}|\d{2,4}年\d{1,2}月\d{1,2}日?)$'
            ).sum()
            if len(s_str) > 0 and date_like / len(s_str) >= 0.4:
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

    @staticmethod
    def _validate_date(y, mo, d):
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

        # 四位西元年
        m = re.match(r'^(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})$', s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return SmartCleaner._validate_date(y, mo, d)

        return value

    @classmethod
    def _clean_currency_value(cls, value):
        if pd.isna(value):
            return value
        s = str(value).strip()
        if s == '' or s.lower() == 'nan':
            return np.nan

        if any(ind in s for ind in cls.CN_MONEY_INDICATORS):
            parsed = cls.parse_chinese_number(s)
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
            if cleaned == '' or cleaned == '-':
                return value
            return float(cleaned)
        except ValueError:
            return value

    @classmethod
    def clean_dataframe(cls, df, options=None):
        options = options or {}
        df_clean = df.copy().reset_index(drop=True)
        actions = []

        # 1. 非資料行
        if options.get('remove_non_data_rows', True):
            try:
                mask = df_clean.apply(cls._is_non_data_row, axis=1)
                removed = int(mask.sum())
                if removed > 0:
                    df_clean = df_clean[~mask].reset_index(drop=True)
                    actions.append(f"✅ 移除 {removed} 行非資料列（警告 / 標題裝飾 / 空行）")
            except Exception as e:
                actions.append(f"⚠️ 非資料行偵測失敗：{e}")

        # 2. Excel 錯誤值
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

        # 3. 全形 → 半形
        if options.get('normalize_width', True):
            cells_changed = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    original = df_clean[col].astype(str)
                    converted = original.apply(cls.to_halfwidth)
                    changed = (original != converted).sum()
                    if changed > 0:
                        df_clean[col] = converted
                        cells_changed += int(changed)
            except Exception:
                pass
            if cells_changed > 0:
                actions.append(f"✅ 轉換 {cells_changed} 個儲存格的全形字元為半形")

        # 4. 儲存格換行
        if options.get('flatten_newlines', True):
            cells_changed = 0
            try:
                for col in df_clean.select_dtypes(include=['object']).columns:
                    original = df_clean[col].astype(str)
                    converted = original.apply(cls.flatten_newlines)
                    changed = (original != converted).sum()
                    if changed > 0:
                        df_clean[col] = converted
                        cells_changed += int(changed)
            except Exception:
                pass
            if cells_changed > 0:
                actions.append(f"✅ 處理 {cells_changed} 個儲存格內的換行符號")

        # 5. 去重
        if options.get('drop_duplicates', True):
            try:
                before = len(df_clean)
                df_clean = df_clean.drop_duplicates().reset_index(drop=True)
                removed = before - len(df_clean)
                if removed > 0:
                    actions.append(f"✅ 移除 {removed} 筆完全重複的列")
            except Exception:
                pass

        # 6. 欄位名稱
        if options.get('clean_columns', True):
            try:
                new_cols = [str(c).strip() for c in df_clean.columns]
                if list(df_clean.columns) != new_cols:
                    df_clean.columns = new_cols
                    actions.append("✅ 清理欄位名稱的頭尾空白")
            except Exception:
                pass

        # 7. 文字 trim
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

        # 8. 民國年 / 日期標準化（直接掃描每一列，不看類型）
        if options.get('normalize_date', True):
            date_fixed = 0
            try:
                for col in df_clean.columns:
                    try:
                        original = df_clean[col].tolist()
                        converted = [
                            cls._convert_minguo_to_western(v) for v in original
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
            except Exception:
                pass

            if date_fixed > 0:
                actions.append(f"✅ 轉換 {date_fixed} 個民國年 / 日期格式為西元")

        # 9. 貨幣清理
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
                actions.append(f"✅ 清理 {currency_fixed} 個貨幣 / 中文數字")

        # 10. 電話標準化
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

        # 11. Email 小寫
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

        # 12. 填補空白
        if options.get('fill_na'):
            fill_value = options.get('fill_value', '')
            df_clean = df_clean.fillna(fill_value)
            actions.append(f"✅ 將空白值填補為「{fill_value}」")

        return df_clean, actions

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
                                anomalies.append({
                                    '欄位': col,
                                    '類型': '數值離群值',
                                    '數量': len(outliers),
                                    '說明': f'超出 [{lo:.2f}, {hi:.2f}] 範圍',
                                })
                except Exception:
                    pass

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

            try:
                s = df[col].dropna().astype(str)
                invalid = s[s.str.contains('無效日期', na=False)]
                if len(invalid) > 0:
                    anomalies.append({
                        '欄位': col,
                        '類型': '無效日期',
                        '數量': len(invalid),
                        '說明': '日期欄位存在不存在的日期（如 2 月 30 日）',
                    })
            except Exception:
                pass

            try:
                s = df[col].dropna().astype(str)
                emoji_like = s[s.str.contains(
                    r'[\U0001F300-\U0001F9FF\u2600-\u27BF]', regex=True, na=False
                )]
                if len(emoji_like) > 0:
                    anomalies.append({
                        '欄位': col,
                        '類型': '含表情符號',
                        '數量': len(emoji_like),
                        '說明': '欄位中含 emoji 或特殊符號，請確認是否為誤輸入',
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
