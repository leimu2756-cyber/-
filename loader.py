"""檔案讀取模組"""
import io
import csv as csv_module
import pandas as pd
from collections import Counter
from utils import format_bytes


# 檔案大小限制
SINGLE_FILE_LIMIT = 50 * 1024 * 1024   # 50 MB
TOTAL_UPLOAD_LIMIT = 200 * 1024 * 1024 # 200 MB
ROW_WARNING_LIMIT = 100000             # 10 萬列


class LoadError(Exception):
	"""自訂讀取錯誤"""
	pass


def _read_csv_robust(file, encoding):
	"""穩健的 CSV 讀取：用眾數欄位數對齊"""
	try:
		file.seek(0)
		raw = file.read()
		if isinstance(raw, bytes):
			text = raw.decode(encoding, errors='replace')
		else:
			text = raw
		if text.startswith('\ufeff'):
			text = text[1:]
		lines = text.splitlines()
		reader = csv_module.reader(lines)
		rows = [r for r in reader]
	except Exception:
		return None

	if not rows:
		return pd.DataFrame()

	col_counts = Counter(len(r) for r in rows)
	target_cols = col_counts.most_common(1)[0][0]
	if target_cols < 2:
		target_cols = max(len(r) for r in rows)

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
	成功：(df, None)
	失敗：(None, "錯誤訊息")
	"""
	if file is None:
		return None, "沒有檔案"

	try:
		file_size = len(file.getvalue())
	except Exception:
		file_size = 0

	if file_size > SINGLE_FILE_LIMIT:
		return None, f"檔案過大（{format_bytes(file_size)}），建議小於 50MB 或分批處理"

	name = file.name.lower()

	# ---------- CSV ----------
	if name.endswith('.csv'):
		for enc in ['utf-8-sig', 'utf-8', 'big5', 'cp950']:
			try:
				df = _read_csv_robust(file, enc)
				if df is not None and not df.empty:
					if len(df) > ROW_WARNING_LIMIT:
						return df, f"檔案超過 {ROW_WARNING_LIMIT:,} 列，建議分批處理"
					return df, None
			except Exception:
				continue
		return None, "CSV 讀取失敗，可能是編碼問題或檔案損毀"

	# ---------- Excel ----------
	if name.endswith(('.xlsx', '.xls')):
		try:
			file.seek(0)
			df = pd.read_excel(file, header=None, engine='openpyxl' if name.endswith('.xlsx') else None)
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
