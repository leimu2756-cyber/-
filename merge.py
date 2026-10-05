"""多檔合併模組"""
import pandas as pd
from cleaner import SmartCleaner
from utils import is_summary_row


def merge_files(files, options=None):
	"""
	合併多個檔案。

	options:
	  - mode: 'strict' 或 'loose'
	  - flag_duplicates: bool
	  - keep_source: bool
	  - merge_sheets: bool
	"""
	options = options or {}
	mode = options.get('mode', 'loose')
	flag_dup = options.get('flag_duplicates', False)
	keep_source = options.get('keep_source', True)

	if not files:
		return {'error': '沒有檔案'}

	merged_list = []
	files_info = []
	all_anomalies = []
	all_actions = []
	total_stats = {
		'files': 0,
		'total_rows': 0,
		'removed_non_data': 0,
		'removed_duplicates': 0,
		'removed_summary': 0,
		'dates_fixed': 0,
		'currency_fixed': 0,
	}

	for i, item in enumerate(files):
		try:
			df_raw = item['df']
			file_name = item['name']

			clean_options = {
				'remove_non_data_rows': True,
				'clean_excel_errors': True,
				'drop_duplicates': True,
				'summary_row_action': 'separate',
				'clean_columns': True,
				'trim_strings': True,
				'normalize_phone': True,
				'normalize_date': True,
				'normalize_email': True,
				'clean_currency': True,
			}
			df_clean, actions, stats, summary_df, total_check = (
				SmartCleaner.clean_dataframe(df_raw, clean_options)
			)

			if keep_source:
				df_clean.insert(0, '來源檔案', file_name)

			merged_list.append(df_clean)
			files_info.append({
				'file': file_name,
				'rows': len(df_clean),
				'summary': summary_df,
				'total_check': total_check,
			})
			all_actions.extend(f"[{file_name}] {action}" for action in actions)
			all_anomalies.extend(
				{'來源檔案': file_name, **anomaly}
				for anomaly in SmartCleaner.detect_anomalies(df_clean)
			)

			total_stats['files'] += 1
			total_stats['total_rows'] += len(df_clean)
			total_stats['removed_non_data'] += stats['rows_removed_non_data']
			total_stats['removed_duplicates'] += stats['rows_removed_duplicate']
			total_stats['removed_summary'] += stats['rows_removed_summary']
			total_stats['dates_fixed'] += stats['dates_fixed']
			total_stats['currency_fixed'] += stats['currency_fixed']
		except Exception as e:
			all_anomalies.append({
				'來源檔案': item.get('name', f'檔案{i + 1}'),
				'欄位': '-',
				'類型': '讀取失敗',
				'數量': 1,
				'說明': str(e),
			})

	if not merged_list:
		return {'error': '所有檔案都無法處理'}

	try:
		if mode == 'strict':
			# 嚴格模式：只保留共同欄位
			common_cols = set(merged_list[0].columns)
			for df in merged_list[1:]:
				common_cols &= set(df.columns)
			common_cols = [col for col in merged_list[0].columns if col in common_cols]
			merged_df = pd.concat(
				[df[common_cols] for df in merged_list], ignore_index=True
			)
		else:
			# 寬鬆模式：union 所有欄位
			merged_df = pd.concat(merged_list, ignore_index=True, sort=False)
	except Exception as e:
		return {'error': f'合併失敗：{e}'}

	if flag_dup:
		try:
			key_cols = [
				col for col in merged_df.columns
				if col not in ('來源檔案', '疑似重複')
			]
			dup_mask = merged_df.duplicated(subset=key_cols, keep=False)
			if '疑似重複' not in merged_df.columns:
				merged_df['疑似重複'] = ''
			merged_df.loc[dup_mask, '疑似重複'] = '是'
			total_stats['duplicates_flagged'] = int(dup_mask.sum())
		except Exception:
			pass

	return {
		'merged_df': merged_df,
		'files_info': files_info,
		'stats': total_stats,
		'anomalies': all_anomalies,
		'actions': all_actions,
		'error': None,
	}
