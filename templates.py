"""行業模板定義"""

TEMPLATES = {
	'通用': {
		'keywords': [],
		'required': [],
		'column_map': {},
		'description': '不套用特定模板，自動偵測欄位類型',
	},
	'記帳本': {
		'keywords': ['日期', '項目', '分類', '金額', '付款方式', '備註'],
		'required': ['日期', '金額'],
		'column_map': {
			'date': ['日期', '交易日', '記帳日', '時間', 'Date'],
			'item': ['項目', '品項', '摘要', '說明', 'Item'],
			'category': ['分類', '類別', '類型', 'Category'],
			'amount': ['金額', '費用', '支出', '收入', '價錢', 'Amount'],
			'payment': ['付款方式', '支付方式', '付款', 'Payment'],
			'note': ['備註', '說明', 'Note', 'Remark'],
		},
		'description': '個人記帳、收支管理',
	},
	'電商訂單': {
		'keywords': ['訂單編號', '客戶', '商品', '數量', '單價', '總金額'],
		'required': ['客戶', '商品'],
		'column_map': {
			'date': ['訂單日期', '下單日', '日期', 'Date'],
			'order_id': ['訂單編號', '訂單號', 'Order ID'],
			'customer': ['客戶', '客戶名稱', '買家', 'Customer'],
			'product': ['商品', '商品名稱', '產品', 'Product'],
			'quantity': ['數量', '訂購數量', '件數', 'Quantity'],
			'unit_price': ['單價', 'Unit Price'],
			'amount': ['總金額', '金額', '小計', 'Total'],
		},
		'description': '電商平台訂單匯出',
	},
	'團購單': {
		'keywords': ['團購', '品項', '數量', '單價', '訂購人', '總金額'],
		'required': ['品項'],
		'column_map': {
			'date': ['日期', '訂購日期', 'Date'],
			'customer': ['訂購人', '姓名', '團員'],
			'product': ['品項', '商品', '產品'],
			'quantity': ['數量', '件數'],
			'unit_price': ['單價'],
			'amount': ['總金額', '金額', '小計'],
		},
		'description': '團購、代購表單',
	},
	'客戶名單': {
		'keywords': ['姓名', '電話', 'Email', '地址', '公司'],
		'required': ['姓名'],
		'column_map': {
			'name': ['姓名', '名稱', '客戶名稱', 'Name'],
			'phone': ['電話', '手機', '聯絡電話', 'Phone'],
			'email': ['Email', '信箱', '電子郵件', 'E-mail'],
			'address': ['地址', '住址', 'Address'],
			'company': ['公司', '公司名稱', 'Company'],
			'note': ['備註', '說明'],
		},
		'description': '客戶聯絡名單',
	},
}


def detect_template(df):
	"""偵測 DataFrame 符合哪個行業模板"""
	try:
		cols = [str(c).strip() for c in df.columns]
	except Exception:
		return {'template': None, 'confidence': 0.0, 'matched': [], 'column_map': {}}

	best = {'template': None, 'confidence': 0.0, 'matched': [], 'column_map': {}}

	for name, spec in TEMPLATES.items():
		if name == '通用':
			continue
		matched = []
		for kw in spec['keywords']:
			for col in cols:
				if kw in col:
					matched.append(kw)
					break
		has_required = all(
			any(req in col for col in cols)
			for req in spec['required']
		)
		if not has_required:
			continue
		confidence = len(matched) / max(len(spec['keywords']), 1)
		if confidence > best['confidence']:
			best = {
				'template': name,
				'confidence': round(confidence, 2),
				'matched': matched,
				'column_map': spec.get('column_map', {}),
			}
	return best


def suggest_column_mapping(df):
	"""自動建議欄位對應"""
	suggestion = {}
	if df is None or len(df.columns) == 0:
		return suggestion

	cols = [str(c).strip() for c in df.columns]

	for canonical, synonyms in TEMPLATES['記帳本']['column_map'].items():
		for col in cols:
			for syn in synonyms:
				if syn.lower() in col.lower():
					suggestion[canonical] = col
					break
			if canonical in suggestion:
				break
	return suggestion
