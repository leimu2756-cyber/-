"""資料分析模組"""
import pandas as pd
import streamlit as st

try:
	import plotly.express as px
	HAS_PLOTLY = True
except ImportError:
	HAS_PLOTLY = False


def build_analytics(df):
	"""回傳分析結果字典"""
	result = {'error': None}

	if df is None or len(df) == 0:
		result['error'] = '沒有資料可分析'
		return result

	# 找日期欄、金額欄、分類欄
	date_col = None
	amount_col = None
	category_col = None

	for col in df.columns:
		c = str(col).lower()
		if not date_col and any(k in c for k in ['日期', 'date', '時間']):
			date_col = col
		if not amount_col and any(k in c for k in ['金額', '費用', '價錢', 'amount', '總計']):
			amount_col = col
		if not category_col and any(k in c for k in ['分類', '類別', '類型', 'category']):
			category_col = col

	result['date_col'] = date_col
	result['amount_col'] = amount_col
	result['category_col'] = category_col

	# 分類圓餅圖
	if category_col and amount_col:
		try:
			cat_df = df.copy()
			cat_df[amount_col] = pd.to_numeric(cat_df[amount_col], errors='coerce')
			cat_sum = cat_df.groupby(category_col)[amount_col].sum().reset_index()
			cat_sum = cat_sum.sort_values(amount_col, ascending=False)
			result['category_summary'] = cat_sum
		except Exception:
			result['category_summary'] = None
	else:
		result['category_summary'] = None

	# 每月收支
	if date_col and amount_col:
		try:
			d = df.copy()
			d[date_col] = pd.to_datetime(d[date_col], errors='coerce')
			d[amount_col] = pd.to_numeric(d[amount_col], errors='coerce')
			d = d.dropna(subset=[date_col])
			d['月份'] = d[date_col].dt.to_period('M').astype(str)
			monthly = d.groupby('月份')[amount_col].sum().reset_index()
			result['monthly_summary'] = monthly
		except Exception:
			result['monthly_summary'] = None
	else:
		result['monthly_summary'] = None

	# 付款方式分布
	pay_col = None
	for col in df.columns:
		c = str(col).lower()
		if any(k in c for k in ['付款', '支付', 'payment']):
			pay_col = col
			break
	if pay_col and amount_col:
		try:
			p = df.copy()
			p[amount_col] = pd.to_numeric(p[amount_col], errors='coerce')
			pay_sum = p.groupby(pay_col)[amount_col].sum().reset_index()
			result['payment_summary'] = pay_sum
		except Exception:
			result['payment_summary'] = None
	else:
		result['payment_summary'] = None

	# 前 10 大項目
	item_col = None
	for col in df.columns:
		c = str(col).lower()
		if any(k in c for k in ['項目', '品項', '產品', '商品', 'item']):
			item_col = col
			break
	if item_col and amount_col:
		try:
			it = df.copy()
			it[amount_col] = pd.to_numeric(it[amount_col], errors='coerce')
			top10 = it.groupby(item_col)[amount_col].sum().reset_index()
			top10 = top10.sort_values(amount_col, ascending=False).head(10)
			result['top10_items'] = top10
		except Exception:
			result['top10_items'] = None
	else:
		result['top10_items'] = None

	return result


def render_analytics(df):
	"""在 Streamlit 渲染分析圖表"""
	res = build_analytics(df)
	if res.get('error'):
		st.warning(res['error'])
		return

	# 圓餅圖
	if res.get('category_summary') is not None and len(res['category_summary']) > 0:
		st.subheader("🥧 各分類金額佔比")
		cat_sum = res['category_summary']
		col1, col2 = st.columns([2, 1])
		with col1:
			if HAS_PLOTLY:
				fig = px.pie(cat_sum, names=cat_sum.columns[0], values=cat_sum.columns[1])
				st.plotly_chart(fig, use_container_width=True)
			else:
				st.bar_chart(cat_sum.set_index(cat_sum.columns[0]))
		with col2:
			st.dataframe(cat_sum, use_container_width=True, hide_index=True)

	# 每月收支
	if res.get('monthly_summary') is not None and len(res['monthly_summary']) > 0:
		st.subheader("📈 每月收支")
		monthly = res['monthly_summary']
		st.bar_chart(monthly.set_index(monthly.columns[0]))

	# 付款方式分布
	if res.get('payment_summary') is not None and len(res['payment_summary']) > 0:
		st.subheader("💳 付款方式分布")
		pay = res['payment_summary']
		if HAS_PLOTLY:
			fig = px.pie(pay, names=pay.columns[0], values=pay.columns[1])
			st.plotly_chart(fig, use_container_width=True)
		else:
			st.bar_chart(pay.set_index(pay.columns[0]))

	# 前 10 大項目
	if res.get('top10_items') is not None and len(res['top10_items']) > 0:
		st.subheader("🏆 前 10 大項目")
		top10 = res['top10_items']
		st.dataframe(top10, use_container_width=True, hide_index=True)
		st.bar_chart(top10.set_index(top10.columns[0]))
