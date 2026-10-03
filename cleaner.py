"""
智慧資料清理引擎 (Smart Data Cleaner)
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

	@staticmethod
	def _match_ratio(series, pattern):
		s = series.dropna().astype(str).str.strip()
		if len(s) == 0:
			return 0.0
		return s.str.match(pattern).sum() / len(s)

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

	@classmethod
	def clean_dataframe(cls, df, options=None):
		options = options or {}
		df_clean = df.copy()
		actions = []

		if options.get('drop_duplicates', True):
			before = len(df_clean)
			df_clean = df_clean.drop_duplicates()
			removed = before - len(df_clean)
			if removed > 0:
				actions.append(f"✅ 移除 {removed} 筆完全重複的列")

		if options.get('clean_columns', True):
			new_cols = [str(c).strip() for c in df_clean.columns]
			if list(df_clean.columns) != new_cols:
				df_clean.columns = new_cols
				actions.append("✅ 清理欄位名稱的頭尾空白")

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

		if options.get('normalize_phone', True):
			for col in df_clean.columns:
				ctype = cls.detect_column_type(df_clean[col])
				if ctype in ('phone_tw', 'mobile_tw'):
					df_clean[col] = (df_clean[col].astype(str)
									 .str.replace(r'[-\s\(\)]', '', regex=True))
					actions.append(f"✅ 標準化「{col}」的電話格式")

		if options.get('normalize_date', True):
			for col in df_clean.columns:
				ctype = cls.detect_column_type(df_clean[col])
				if ctype == 'date':
					try:
						df_clean[col] = (pd.to_datetime(df_clean[col], errors='coerce')
										 .dt.strftime('%Y-%m-%d'))
						actions.append(f"✅ 標準化「{col}」的日期為 YYYY-MM-DD")
					except Exception:
						pass

		if options.get('normalize_email', True):
			for col in df_clean.columns:
				ctype = cls.detect_column_type(df_clean[col])
				if ctype == 'email':
					df_clean[col] = df_clean[col].astype(str).str.lower()
					actions.append(f"✅ 將「{col}」的 Email 轉為小寫")

		if options.get('fill_na'):
			fill_value = options.get('fill_value', '')
			df_clean = df_clean.fillna(fill_value)
			actions.append(f"✅ 將空白值填補為「{fill_value}」")

		return df_clean, actions

	@classmethod
	def detect_anomalies(cls, df):
		anomalies = []
		for col in df.columns:
			ctype = cls.detect_column_type(df[col])

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

		return anomalies

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
