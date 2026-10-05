"""報告產生模組"""
import pandas as pd


def build_clean_report(stats, total_check=None, template_info=None):
	"""建立清理報告 DataFrame"""
	rows = [
		("移除非資料列", stats.get('rows_removed_non_data', 0), "列"),
		("移除重複列", stats.get('rows_removed_duplicate', 0), "列"),
		("移除彙總列", stats.get('rows_removed_summary', 0), "列"),
		("Excel 錯誤值清理", stats.get('excel_errors_fixed', 0), "個"),
		("全形轉半形", stats.get('cells_halfwidth', 0), "格"),
		("換行符號處理", stats.get('cells_newline', 0), "格"),
		("日期格式轉換", stats.get('dates_fixed', 0), "筆"),
		("貨幣 / 中文數字清理", stats.get('currency_fixed', 0), "筆"),
		("疑似重複標記", stats.get('duplicates_flagged', 0), "筆"),
	]
	df = pd.DataFrame(rows, columns=["項目", "數量", "單位"])
	df = df[df["數量"] > 0]
	return df


def build_anomaly_table(anomalies):
	"""建立異常清單 DataFrame"""
	if not anomalies:
		return pd.DataFrame()
	return pd.DataFrame(anomalies)


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
