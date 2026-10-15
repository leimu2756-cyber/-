"""多檔合併模組（支援垂直堆疊 + 水平 JOIN）"""
import pandas as pd
from cleaner import SmartCleaner
from utils import is_summary_row, standardize_columns


def detect_merge_strategy(files):
    """偵測多個檔案該用哪種合併策略（先做欄位標準化）"""
    if not files or len(files) < 2:
        return {'strategy': 'stack', 'common_cols': [], 'all_cols': {}, 'reason': '只有一個檔案'}

    all_cols = {}
    for item in files:
        name = item['name']
        df = item['df']
        # ★ 關鍵：先做欄位標準化，再計算共同欄位
        try:
            df_std = standardize_columns(df.copy(), enabled=True)
        except Exception:
            df_std = df
        cols = [str(c).strip() for c in df_std.columns if str(c).strip() != '來源檔案']
        all_cols[name] = cols

    col_sets = [set(cols) for cols in all_cols.values()]
    if all(s == col_sets[0] for s in col_sets):
        return {
            'strategy': 'stack',
            'common_cols': list(col_sets[0]),
            'all_cols': all_cols,
            'reason': '所有檔案欄位相同，適合垂直堆疊',
        }

    common = col_sets[0]
    for s in col_sets[1:]:
        common &= s
    common = list(common)

    if common:
        return {
            'strategy': 'ask',
            'common_cols': common,
            'all_cols': all_cols,
            'reason': f'偵測到共同欄位：{", ".join(common)}。可垂直堆疊或水平關聯。',
        }

    return {
        'strategy': 'stack',
        'common_cols': [],
        'all_cols': all_cols,
        'reason': '沒有共同欄位，只能垂直堆疊',
    }


def suggest_join_key(files, common_cols):
    """
    從共同欄位中，建議最適合當 JOIN key 的欄位
    優先順序：
      1. 欄位名稱含「編號 / ID / 代號 / 序號」→ 優先
      2. 欄位名稱含「電話 / Email / 帳號」→ 次優先
      3. 唯一值比例越高越適合
      4. 排除「單價、金額、數量、日期」等不適合當 key 的欄位
    """
    if not common_cols:
        return None

    EXCLUDE_KEYWORDS = [
        '單價', '单价', '金額', '金额', '數量', '数量', '價錢', '价钱',
        '價格', '价格', '總計', '总计', '日期', '時間', '时间',
        '備註', '备注', '說明', '说明',
    ]

    PRIORITY_KEYWORDS = [
        '編號', '编号', 'id', '序號', '代號',
    ]
    SECONDARY_KEYWORDS = [
        '電話', '手機', 'email', '帳號',
    ]

    scores = {}
    for col in common_cols:
        col_lower = str(col).lower()

        if any(kw in col_lower for kw in EXCLUDE_KEYWORDS):
            continue

        try:
            ratios = []
            for item in files:
                df = item['df']
                if col not in df.columns:
                    continue
                n = len(df)
                u = df[col].nunique(dropna=True)
                ratios.append(u / max(n, 1))
            if not ratios:
                continue

            avg_ratio = sum(ratios) / len(ratios)
            score = avg_ratio

            if any(kw in col_lower for kw in PRIORITY_KEYWORDS):
                score += 10.0
            elif any(kw in col_lower for kw in SECONDARY_KEYWORDS):
                score += 5.0

            scores[col] = score
        except Exception:
            continue

    if not scores:
        return common_cols[0] if common_cols else None

    return max(scores.items(), key=lambda x: x[1])[0]


def merge_files(files, options=None):
    options = options or {}
    mode = options.get('mode', 'stack')
    duplicate_mode = options.get('duplicate_mode', 'mark')
    keep_source = options.get('keep_source', True)

    if not files:
        return {'error': '沒有檔案'}

    # 第一步：清理每個檔案
    cleaned_list = []
    files_info = []
    all_anomalies = []
    all_actions = []
    total_stats = {
        'files': 0,
        'merged_rows': 0,
        'per_file_rows': {},
        'removed_non_data': 0,
        'removed_summary': 0,
        'dates_fixed': 0,
        'currency_fixed': 0,
        'duplicates_flagged': 0,
        'duplicates_dropped': 0,
    }

    for i, item in enumerate(files):
        try:
            df_raw = item['df']
            file_name = item['name']

            clean_options = {
                'remove_non_data_rows': True,
                'clean_excel_errors': True,
                'duplicate_mode': duplicate_mode,
                'summary_row_action': 'separate',
                'clean_columns': True,
                'standardize_columns': True,
                'trim_strings': True,
                'normalize_phone': True,
                'normalize_date': True,
                'normalize_email': True,
                'clean_currency': True,
            }

            df_clean, actions, stats, summary_df, total_check = SmartCleaner.clean_dataframe(
                df_raw, clean_options
            )

            cleaned_list.append({
                'name': file_name,
                'df': df_clean,
                'summary': summary_df,
                'total_check': total_check,
            })
            files_info.append({
                'file': file_name,
                'rows': len(df_clean),
                'summary': summary_df,
                'total_check': total_check,
            })
            all_actions.extend([f"[{file_name}] {a}" for a in actions])
            all_anomalies.extend(
                SmartCleaner.detect_anomalies(
                    df_clean,
                    source_name=file_name,
                    total_check=total_check,
                )
            )

            total_stats['files'] += 1
            total_stats['per_file_rows'][file_name] = len(df_clean)
            total_stats['removed_non_data'] += stats.get('rows_removed_non_data', 0)
            total_stats['removed_summary'] += stats.get('rows_removed_summary', 0)
            total_stats['dates_fixed'] += stats.get('dates_fixed', 0)
            total_stats['currency_fixed'] += stats.get('currency_fixed', 0)
            total_stats['duplicates_flagged'] += stats.get('duplicates_flagged', 0)
            total_stats['duplicates_dropped'] += stats.get('duplicates_dropped', 0)

        except Exception as e:
            all_anomalies.append({
                '来源档案': item.get('name', f'檔案{i+1}'),
                '列号': '-',
                '问题类型': '讀取失敗',
                '说明': str(e),
                '建议': '請確認檔案格式',
            })

    if not cleaned_list:
        return {'error': '所有檔案都無法處理'}

    # 第二步：合併
    try:
        if mode == 'join':
            merged_df = _join_dataframes(cleaned_list, options)
        else:
            merged_df = _stack_dataframes(cleaned_list, keep_source)
    except Exception as e:
        return {'error': f'合併失敗：{e}'}

    total_stats['merged_rows'] = len(merged_df)

    return {
        'merged_df': merged_df,
        'files_info': files_info,
        'stats': total_stats,
        'anomalies': all_anomalies,
        'actions': all_actions,
        'error': None,
    }


def _stack_dataframes(cleaned_list, keep_source):
    """垂直堆疊"""
    dfs = []
    for item in cleaned_list:
        df = item['df'].copy()
        if '疑似重複' in df.columns:
            df = df.drop(columns=['疑似重複'])
        if keep_source:
            df.insert(0, '來源檔案', item['name'])
        dfs.append(df)

    if not dfs:
        return pd.DataFrame()

    result = pd.concat(dfs, ignore_index=True, sort=False)
    return result


def _join_dataframes(cleaned_list, options):
    """水平 JOIN"""
    join_type = options.get('join_type', 'left')
    join_key = options.get('join_key')
    base_file = options.get('base_file')

    if not join_key:
        raise ValueError('JOIN 模式需要指定 key 欄位')

    ordered = list(cleaned_list)
    if base_file and join_type in ('left', 'right'):
        ordered.sort(key=lambda x: 0 if x['name'] == base_file else 1)

    first = ordered[0]
    result = first['df'].copy()
    if '疑似重複' in result.columns:
        result = result.drop(columns=['疑似重複'])
    result['_來源'] = first['name']

    for item in ordered[1:]:
        df_next = item['df'].copy()
        if '疑似重複' in df_next.columns:
            df_next = df_next.drop(columns=['疑似重複'])

        if join_key not in result.columns:
            raise ValueError(f'基礎表沒有欄位「{join_key}」')
        if join_key not in df_next.columns:
            raise ValueError(f'{item["name"]} 沒有欄位「{join_key}」')

        suffix_b = f'_{item["name"].replace(".csv", "").replace(".xlsx", "")}'

        try:
            result = pd.merge(
                result,
                df_next,
                on=join_key,
                how=join_type,
                suffixes=('', suffix_b),
            )
        except Exception as e:
            raise ValueError(f'合併 {item["name"]} 失敗：{e}')

        result['_來源'] = result['_來源'].fillna('') + ',' + item['name']
        result['_來源'] = result['_來源'].str.strip(',')

    if '_來源' in result.columns:
        result = result.rename(columns={'_來源': '來源檔案'})
        cols = ['來源檔案'] + [c for c in result.columns if c != '來源檔案']
        result = result[cols]

    return result
