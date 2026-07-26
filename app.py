"""
青色申告 複式簿記 - ローカル版
Flask + SQLite でローカルPCで動作する複式簿記アプリケーション
"""
import os
import sqlite3
import json
from datetime import datetime, date
from flask import Flask, request, jsonify, send_from_directory, g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'bookkeeping.db')

app = Flask(__name__, static_folder='static', static_url_path='/static')


# ============ DB connection ============
def get_db():
    if 'db' not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(err):
    db = g.pop('db', None)
    if db is not None:
        db.close()


# ============ Schema Init ============
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category IN ('asset','liability','equity','revenue','expense')),
  subcategory TEXT,
  bs_pl TEXT NOT NULL CHECK (bs_pl IN ('BS','PL')),
  normal_balance TEXT NOT NULL CHECK (normal_balance IN ('debit','credit')),
  aoiro_line TEXT,
  is_taxable INTEGER DEFAULT 0,
  description TEXT,
  display_order INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS partners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT CHECK (kind IN ('customer','vendor','both','other')),
  invoice_registered INTEGER DEFAULT 0,
  invoice_number TEXT,
  memo TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journal_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_date TEXT NOT NULL,
  slip_no TEXT,
  description TEXT NOT NULL,
  partner_id INTEGER REFERENCES partners(id) ON DELETE SET NULL,
  source TEXT DEFAULT 'manual',
  source_ref TEXT,
  fiscal_year INTEGER NOT NULL DEFAULT 2026,
  is_locked INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_je_date ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_je_fy ON journal_entries(fiscal_year);

CREATE TABLE IF NOT EXISTS journal_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('debit','credit')),
  account_code TEXT NOT NULL REFERENCES accounts(code),
  amount INTEGER NOT NULL CHECK (amount >= 0),
  memo TEXT
);
CREATE INDEX IF NOT EXISTS idx_jl_entry ON journal_lines(entry_id);
CREATE INDEX IF NOT EXISTS idx_jl_account ON journal_lines(account_code);

CREATE TABLE IF NOT EXISTS entry_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  template_key TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  label TEXT NOT NULL,
  icon TEXT,
  debit_account TEXT REFERENCES accounts(code),
  credit_account TEXT REFERENCES accounts(code),
  default_description TEXT,
  display_order INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS fixed_assets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  acquired_date TEXT NOT NULL,
  acquisition_cost INTEGER NOT NULL,
  useful_life_years INTEGER NOT NULL,
  depreciation_method TEXT DEFAULT 'straight_line',
  book_value INTEGER,
  memo TEXT
);

CREATE TABLE IF NOT EXISTS opening_balances (
  account_code TEXT PRIMARY KEY REFERENCES accounts(code),
  fiscal_year INTEGER NOT NULL,
  amount INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fiscal_settings (
  fiscal_year INTEGER PRIMARY KEY,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  business_name TEXT,
  proprietor_name TEXT,
  address TEXT,
  is_closed INTEGER DEFAULT 0
);
"""

SEED_ACCOUNTS = [
    # 資産
    ('1110','現金','asset','流動資産','BS','debit','BS_1_cash',10),
    ('1120','普通預金','asset','流動資産','BS','debit','BS_2_bank_ord',20),
    ('1121','事業用口座','asset','流動資産','BS','debit','BS_2_bank_ord',21),
    ('1130','当座預金','asset','流動資産','BS','debit','BS_2_bank_cur',30),
    ('1140','定期預金','asset','流動資産','BS','debit','BS_3_bank_fix',40),
    ('1210','売掛金','asset','流動資産','BS','debit','BS_4_receivable',50),
    ('1220','前払金','asset','流動資産','BS','debit','BS_5_prepaid',60),
    ('1230','立替金','asset','流動資産','BS','debit','BS_6_advance',70),
    ('1240','仮払金','asset','流動資産','BS','debit','BS_7_temp_pay',80),
    ('1310','事業主貸','asset','その他','BS','debit','BS_owner_lend',90),
    ('1410','建物','asset','固定資産','BS','debit','BS_building',100),
    ('1420','工具器具備品','asset','固定資産','BS','debit','BS_equipment',110),
    ('1430','車両運搬具','asset','固定資産','BS','debit','BS_vehicle',120),
    ('1440','ソフトウェア','asset','固定資産','BS','debit','BS_software',130),
    ('1450','一括償却資産','asset','固定資産','BS','debit','BS_equipment',140),
    # 負債
    ('2110','買掛金','liability','流動負債','BS','credit','BS_payable',210),
    ('2120','未払金','liability','流動負債','BS','credit','BS_unpaid',220),
    ('2130','未払費用','liability','流動負債','BS','credit','BS_unpaid_exp',230),
    ('2140','前受金','liability','流動負債','BS','credit','BS_received_adv',240),
    ('2150','預り金','liability','流動負債','BS','credit','BS_deposit_recv',250),
    ('2160','仮受金','liability','流動負債','BS','credit','BS_temp_recv',260),
    ('2210','借入金','liability','固定負債','BS','credit','BS_loan',270),
    # 資本
    ('3110','元入金','equity','資本','BS','credit','BS_capital',310),
    ('3120','事業主借','equity','資本','BS','credit','BS_owner_borrow',320),
    ('3130','青色申告特別控除前所得','equity','資本','BS','credit','BS_income_before',330),
    # 収益
    ('4110','売上高','revenue','売上','PL','credit','PL_sales_1',410),
    ('4210','雑収入','revenue','その他収益','PL','credit','PL_misc_income',420),
    ('4220','受取利息','revenue','その他収益','PL','credit','PL_misc_income',430),
    # 費用
    ('5110','租税公課','expense','経費','PL','debit','PL_tax_public',510),
    ('5120','荷造運賃','expense','経費','PL','debit','PL_packing',520),
    ('5130','水道光熱費','expense','経費','PL','debit','PL_utilities',530),
    ('5140','旅費交通費','expense','経費','PL','debit','PL_travel',540),
    ('5150','通信費','expense','経費','PL','debit','PL_communication',550),
    ('5160','広告宣伝費','expense','経費','PL','debit','PL_advertising',560),
    ('5170','接待交際費','expense','経費','PL','debit','PL_entertainment',570),
    ('5180','損害保険料','expense','経費','PL','debit','PL_insurance',580),
    ('5190','修繕費','expense','経費','PL','debit','PL_repair',590),
    ('5200','消耗品費','expense','経費','PL','debit','PL_supplies',600),
    ('5210','減価償却費','expense','経費','PL','debit','PL_depreciation',610),
    ('5220','福利厚生費','expense','経費','PL','debit','PL_welfare',620),
    ('5230','給料賃金','expense','経費','PL','debit','PL_salary',630),
    ('5240','外注工賃','expense','経費','PL','debit','PL_outsourcing',640),
    ('5250','利子割引料','expense','経費','PL','debit','PL_interest',650),
    ('5260','地代家賃','expense','経費','PL','debit','PL_rent',660),
    ('5270','貸倒金','expense','経費','PL','debit','PL_bad_debt',670),
    ('5280','会議費','expense','経費','PL','debit','PL_other',680),
    ('5290','新聞図書費','expense','経費','PL','debit','PL_other',690),
    ('5300','支払手数料','expense','経費','PL','debit','PL_other',700),
    ('5310','研修費','expense','経費','PL','debit','PL_other',710),
    ('5320','雑費','expense','経費','PL','debit','PL_misc',720),
]

SEED_TEMPLATES = [
    ('sales_transfer','収入','売上（振込入金）','banknote','1121','4110','売上代金の入金',10),
    ('sales_cash','収入','売上（現金）','japanese-yen','1110','4110','売上（現金）',20),
    ('sales_credit','収入','売上（掛売り）','file-text','1210','4110','売上（後日入金）',30),
    ('receivable_collect','収入','売掛金の回収','wallet','1121','1210','売掛金の入金',40),
    ('advance_received','収入','前受金の受取','arrow-down-circle','1121','2140','前受金',50),
    ('exp_communication','経費','通信費（スマホ/ネット）','wifi','5150','1121','通信費',110),
    ('exp_utilities','経費','水道光熱費','zap','5130','1121','水道光熱費',120),
    ('exp_rent','経費','家賃・地代','home','5260','1121','事務所家賃',130),
    ('exp_travel','経費','旅費交通費','train-front','5140','1110','電車・タクシー代',140),
    ('exp_supplies','経費','消耗品費','package','5200','1110','消耗品購入',150),
    ('exp_books','経費','新聞図書費','book-open','5290','1110','書籍購入',160),
    ('exp_meeting','経費','会議費・カフェ代','coffee','5280','1110','打合せ費用',170),
    ('exp_entertainment','経費','接待交際費','users','5170','1121','接待費',180),
    ('exp_advertising','経費','広告宣伝費','megaphone','5160','1121','広告費',190),
    ('exp_outsourcing','経費','外注工賃','user-check','5240','1121','外注費',200),
    ('exp_fees','経費','支払手数料','receipt','5300','1121','振込手数料など',210),
    ('exp_software','経費','ソフト・SaaS','laptop','5200','1121','SaaS利用料',220),
    ('exp_insurance','経費','損害保険料','shield','5180','1121','保険料',230),
    ('exp_tax','経費','租税公課','landmark','5110','1121','税金',240),
    ('exp_misc','経費','雑費','more-horizontal','5320','1110','雑費',250),
    ('owner_expense','事業主','事業主が個人で立替払い','user','5200','3120','個人カード払い→事業主借',310),
    ('owner_draw','事業主','事業主貸（生活費など引出）','arrow-up-right','1310','1121','事業主貸',320),
    ('owner_deposit','事業主','事業主借（個人資金投入）','arrow-down-left','1121','3120','事業主借',330),
    ('cash_deposit','振替','現金→預金へ入金','arrow-right','1121','1110','預入',410),
    ('cash_withdraw','振替','預金→現金を引出','arrow-left','1110','1121','引出',420),
    ('buy_equipment','資産','備品購入(10万円未満は消耗品費)','box','1420','1121','備品購入',430),
]


def init_db():
    """初回起動時にスキーマとシードデータをセットアップ"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA_SQL)
    # Seed accounts
    cur = con.execute("SELECT COUNT(*) FROM accounts")
    if cur.fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO accounts (code, name, category, subcategory, bs_pl, normal_balance, aoiro_line, display_order) VALUES (?,?,?,?,?,?,?,?)",
            SEED_ACCOUNTS
        )
        # Seed opening balances (all 0)
        con.executemany(
            "INSERT INTO opening_balances (account_code, fiscal_year, amount) VALUES (?, 2026, 0)",
            [(a[0],) for a in SEED_ACCOUNTS if a[4] == 'BS']
        )
        # Seed templates
        con.executemany(
            "INSERT INTO entry_templates (template_key, category, label, icon, debit_account, credit_account, default_description, display_order) VALUES (?,?,?,?,?,?,?,?)",
            SEED_TEMPLATES
        )
        # Fiscal settings
        con.execute(
            "INSERT INTO fiscal_settings (fiscal_year, start_date, end_date, business_name) VALUES (2026, '2026-01-01', '2026-12-31', 'フリーランス事業')"
        )
        con.commit()
        print(f"[init] Database initialized at {DB_PATH}")
    con.close()


# ============ Helper: query executor ============
def query(sql, params=(), one=False, commit=False):
    db = get_db()
    cur = db.execute(sql, params)
    if commit:
        db.commit()
        return cur.lastrowid
    rows = cur.fetchall()
    return dict(rows[0]) if rows and one else [dict(r) for r in rows]


# ============ Routes: static ============
@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')


# ============ API: reference data ============
@app.route('/api/templates')
def api_templates():
    sql = """
    SELECT t.id, t.template_key, t.category, t.label, t.icon,
           t.debit_account, da.name AS debit_name,
           t.credit_account, ca.name AS credit_name,
           t.default_description, t.display_order
    FROM entry_templates t
    LEFT JOIN accounts da ON da.code = t.debit_account
    LEFT JOIN accounts ca ON ca.code = t.credit_account
    WHERE t.is_active = 1
    ORDER BY t.category, t.display_order
    """
    return jsonify(query(sql))


@app.route('/api/accounts')
def api_accounts():
    sql = """
    SELECT code, name, category, subcategory, bs_pl, normal_balance, display_order
    FROM accounts WHERE is_active = 1
    ORDER BY display_order, code
    """
    return jsonify(query(sql))


# ============ API: Journal Entries ============
@app.route('/api/entries', methods=['POST'])
def api_insert_entry():
    """簡単入力：ヘッダ+2明細で1仕訳を登録"""
    d = request.get_json()
    db = get_db()
    cur = db.execute(
        "INSERT INTO journal_entries (entry_date, description, source, fiscal_year) VALUES (?,?,?,?)",
        (d['entry_date'], d['description'], d.get('source', 'simple'), d['fiscal_year'])
    )
    entry_id = cur.lastrowid
    db.execute(
        "INSERT INTO journal_lines (entry_id, line_no, side, account_code, amount) VALUES (?, 1, 'debit', ?, ?)",
        (entry_id, d['debit_account'], int(d['amount']))
    )
    db.execute(
        "INSERT INTO journal_lines (entry_id, line_no, side, account_code, amount) VALUES (?, 2, 'credit', ?, ?)",
        (entry_id, d['credit_account'], int(d['amount']))
    )
    db.commit()
    return jsonify({'entry_id': entry_id})


@app.route('/api/entries/<int:entry_id>', methods=['DELETE'])
def api_delete_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM journal_entries WHERE id = ? AND is_locked = 0", (entry_id,))
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/entries/<int:entry_id>', methods=['GET'])
def api_get_entry(entry_id):
    """1仕訳の詳細（明細含む）を返す"""
    entry = query("SELECT * FROM journal_entries WHERE id = ?", (entry_id,), one=True)
    if not entry:
        return jsonify({'error': 'not found'}), 404
    lines = query(
        """SELECT jl.id, jl.line_no, jl.side, jl.account_code, jl.amount, jl.memo,
                  a.name AS account_name
           FROM journal_lines jl JOIN accounts a ON a.code = jl.account_code
           WHERE jl.entry_id = ?
           ORDER BY jl.line_no""",
        (entry_id,))
    entry['lines'] = lines
    return jsonify(entry)


@app.route('/api/entries/<int:entry_id>', methods=['PATCH'])
def api_update_entry(entry_id):
    """仕訳を修正（日付/摘要/勘定科目/金額）"""
    d = request.get_json()
    db = get_db()
    # 存在チェック＆ロック確認
    row = db.execute("SELECT is_locked FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({'error': 'not found'}), 404
    if row['is_locked']:
        return jsonify({'error': 'locked'}), 400

    # ヘッダ更新
    fields = []
    values = []
    for k in ('entry_date', 'description'):
        if k in d:
            fields.append(f"{k} = ?")
            values.append(d[k])
    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(entry_id)
        db.execute(f"UPDATE journal_entries SET {', '.join(fields)} WHERE id = ?", values)

    # 明細更新（単純化: 借方/貸方の科目・金額を丸ごと入れ替え）
    if 'debit_account' in d and 'credit_account' in d and 'amount' in d:
        db.execute("DELETE FROM journal_lines WHERE entry_id = ?", (entry_id,))
        amount = int(d['amount'])
        db.execute(
            "INSERT INTO journal_lines (entry_id, line_no, side, account_code, amount) VALUES (?, 1, 'debit', ?, ?)",
            (entry_id, d['debit_account'], amount)
        )
        db.execute(
            "INSERT INTO journal_lines (entry_id, line_no, side, account_code, amount) VALUES (?, 2, 'credit', ?, ?)",
            (entry_id, d['credit_account'], amount)
        )
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/journal')
def api_journal():
    fy = int(request.args.get('fiscal_year', 2026))
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    sql = """
    SELECT e.id, e.entry_date, e.description, e.source,
      (SELECT GROUP_CONCAT(a.name || ' ' || jl.amount, ' / ')
       FROM journal_lines jl JOIN accounts a ON a.code = jl.account_code
       WHERE jl.entry_id = e.id AND jl.side = 'debit') AS debit_summary,
      (SELECT GROUP_CONCAT(a.name || ' ' || jl.amount, ' / ')
       FROM journal_lines jl JOIN accounts a ON a.code = jl.account_code
       WHERE jl.entry_id = e.id AND jl.side = 'credit') AS credit_summary,
      (SELECT SUM(amount) FROM journal_lines WHERE entry_id = e.id AND side = 'debit') AS amount
    FROM journal_entries e
    WHERE e.fiscal_year = ?
      AND (? IS NULL OR e.entry_date >= ?)
      AND (? IS NULL OR e.entry_date <= ?)
    ORDER BY e.entry_date DESC, e.id DESC
    LIMIT 500
    """
    return jsonify(query(sql, (fy, date_from, date_from, date_to, date_to)))


# ============ API: Ledger ============
@app.route('/api/ledger')
def api_ledger():
    """
    複数科目対応の総勘定元帳。
    - account_codes: カンマ区切りで複数指定可（例: "1121,4110,5150"）
    - fiscal_year: 会計年度
    - date_from / date_to: 期間フィルタ（任意）
    レスポンスは科目ごとにグループ化:
      [{ account: {code,name,category}, opening, closing, rows: [...] }, ...]
    """
    codes_param = request.args.get('account_codes') or request.args.get('account_code') or ''
    codes = [c.strip() for c in codes_param.split(',') if c.strip()]
    fy = int(request.args.get('fiscal_year', 2026))
    date_from = request.args.get('date_from') or None
    date_to = request.args.get('date_to') or None
    if not codes:
        return jsonify([])

    result = []
    for code in codes:
        acc = query("SELECT code, name, category, subcategory, normal_balance FROM accounts WHERE code = ?", (code,), one=True)
        if not acc:
            continue
        ob_row = query("SELECT amount FROM opening_balances WHERE account_code = ? AND fiscal_year = ?", (code, fy), one=True)
        opening = int(ob_row['amount']) if ob_row else 0

        # 日付範囲外の期首調整（date_from が指定されていれば、そこまでの累計を期首に加算）
        prior_opening_delta = 0
        if date_from:
            prior_rows = query("""
                SELECT jl.side, jl.amount
                FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
                WHERE jl.account_code = ? AND je.fiscal_year = ? AND je.entry_date < ?
            """, (code, fy, date_from))
            for r in prior_rows:
                d = r['amount'] if r['side'] == 'debit' else 0
                c = r['amount'] if r['side'] == 'credit' else 0
                if acc['normal_balance'] == 'debit':
                    prior_opening_delta += d - c
                else:
                    prior_opening_delta += c - d
        opening_for_period = opening + prior_opening_delta

        sql = """
        SELECT je.entry_date, je.id AS entry_id, je.description,
          jl.side, jl.amount,
          (SELECT GROUP_CONCAT(a2.name, ' / ')
           FROM journal_lines jl2 JOIN accounts a2 ON a2.code = jl2.account_code
           WHERE jl2.entry_id = je.id AND jl2.side != jl.side) AS counter_account
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE jl.account_code = ? AND je.fiscal_year = ?
          AND (? IS NULL OR je.entry_date >= ?)
          AND (? IS NULL OR je.entry_date <= ?)
        ORDER BY je.entry_date, je.id
        """
        rows = query(sql, (code, fy, date_from, date_from, date_to, date_to))
        balance = opening_for_period
        entries = []
        for r in rows:
            debit = r['amount'] if r['side'] == 'debit' else 0
            credit = r['amount'] if r['side'] == 'credit' else 0
            if acc['normal_balance'] == 'debit':
                balance += debit - credit
            else:
                balance += credit - debit
            entries.append({
                'entry_date': r['entry_date'],
                'entry_id': r['entry_id'],
                'description': r['description'],
                'counter_account': r['counter_account'],
                'debit': debit,
                'credit': credit,
                'running_balance': balance
            })
        result.append({
            'account': {'code': acc['code'], 'name': acc['name'], 'category': acc['category'],
                        'subcategory': acc['subcategory'], 'normal_balance': acc['normal_balance']},
            'opening': opening_for_period,
            'closing': balance,
            'rows': entries
        })
    return jsonify(result)


# ============ API: Dashboard ============
@app.route('/api/dashboard/summary')
def api_dashboard_summary():
    fy = int(request.args.get('fiscal_year', 2026))
    # 売上/経費集計
    sql = """
    SELECT a.category,
      SUM(CASE WHEN jl.side='credit' THEN jl.amount ELSE 0 END) -
      SUM(CASE WHEN jl.side='debit' THEN jl.amount ELSE 0 END) AS revenue_bal,
      SUM(CASE WHEN jl.side='debit' THEN jl.amount ELSE 0 END) -
      SUM(CASE WHEN jl.side='credit' THEN jl.amount ELSE 0 END) AS expense_bal
    FROM accounts a
    JOIN journal_lines jl ON jl.account_code = a.code
    JOIN journal_entries je ON je.id = jl.entry_id
    WHERE a.bs_pl='PL' AND je.fiscal_year = ?
    GROUP BY a.category
    """
    rows = query(sql, (fy,))
    revenue = sum((int(r['revenue_bal'] or 0) for r in rows if r['category'] == 'revenue'), 0)
    expense = sum((int(r['expense_bal'] or 0) for r in rows if r['category'] == 'expense'), 0)
    cnt = query("SELECT COUNT(*) AS c FROM journal_entries WHERE fiscal_year = ?", (fy,), one=True)
    return jsonify({
        'total_revenue': revenue,
        'total_expense': expense,
        'net_income': revenue - expense,
        'entry_count': cnt['c']
    })


@app.route('/api/dashboard/monthly')
def api_dashboard_monthly():
    fy = int(request.args.get('fiscal_year', 2026))
    sql = """
    SELECT strftime('%Y-%m', je.entry_date) AS month,
      SUM(CASE WHEN a.category='revenue' THEN
        (CASE WHEN jl.side='credit' THEN jl.amount ELSE -jl.amount END) ELSE 0 END) AS revenue,
      SUM(CASE WHEN a.category='expense' THEN
        (CASE WHEN jl.side='debit' THEN jl.amount ELSE -jl.amount END) ELSE 0 END) AS expense
    FROM journal_entries je
    JOIN journal_lines jl ON jl.entry_id = je.id
    JOIN accounts a ON a.code = jl.account_code
    WHERE je.fiscal_year = ? AND a.bs_pl='PL'
    GROUP BY 1
    """
    data = {r['month']: r for r in query(sql, (fy,))}
    result = []
    for m in range(1, 13):
        key = f"{fy}-{m:02d}"
        d = data.get(key)
        result.append({
            'month': key,
            'revenue': int(d['revenue'] or 0) if d else 0,
            'expense': int(d['expense'] or 0) if d else 0,
        })
    return jsonify(result)


# ============ API: P/L ============
@app.route('/api/reports/pl')
def api_pl():
    fy = int(request.args.get('fiscal_year', 2026))
    sql = """
    SELECT a.code, a.name, a.category, a.normal_balance, a.display_order,
      COALESCE(SUM(CASE WHEN jl.side = 'debit' THEN jl.amount ELSE 0 END), 0) AS debit_sum,
      COALESCE(SUM(CASE WHEN jl.side = 'credit' THEN jl.amount ELSE 0 END), 0) AS credit_sum
    FROM accounts a
    LEFT JOIN journal_lines jl ON jl.account_code = a.code
    LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.fiscal_year = ?
    WHERE a.bs_pl = 'PL'
    GROUP BY a.code, a.name, a.category, a.normal_balance, a.display_order
    HAVING debit_sum > 0 OR credit_sum > 0
    ORDER BY a.category DESC, a.display_order
    """
    rows = query(sql, (fy,))
    result = []
    for r in rows:
        d = int(r['debit_sum'] or 0)
        c = int(r['credit_sum'] or 0)
        bal = (c - d) if r['normal_balance'] == 'credit' else (d - c)
        result.append({
            'code': r['code'], 'name': r['name'], 'category': r['category'],
            'display_order': r['display_order'], 'balance': bal
        })
    return jsonify(result)


# ============ API: B/S ============
@app.route('/api/reports/bs')
def api_bs():
    fy = int(request.args.get('fiscal_year', 2026))
    # PL 当期純利益
    pl_sql = """
    SELECT a.category,
      SUM(CASE WHEN jl.side='credit' THEN jl.amount ELSE 0 END) AS c,
      SUM(CASE WHEN jl.side='debit' THEN jl.amount ELSE 0 END) AS d
    FROM accounts a
    LEFT JOIN journal_lines jl ON jl.account_code = a.code
    LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.fiscal_year = ?
    WHERE a.bs_pl = 'PL'
    GROUP BY a.category
    """
    net_income = 0
    for r in query(pl_sql, (fy,)):
        if r['category'] == 'revenue':
            net_income += int(r['c'] or 0) - int(r['d'] or 0)
        elif r['category'] == 'expense':
            net_income -= int(r['d'] or 0) - int(r['c'] or 0)

    # BS 各科目の期首＋増減
    sql = """
    SELECT a.code, a.name, a.category, a.subcategory, a.display_order, a.normal_balance,
      COALESCE(ob.amount, 0) AS opening,
      COALESCE(SUM(CASE WHEN jl.side='debit' THEN jl.amount ELSE 0 END), 0) AS debit_sum,
      COALESCE(SUM(CASE WHEN jl.side='credit' THEN jl.amount ELSE 0 END), 0) AS credit_sum
    FROM accounts a
    LEFT JOIN journal_lines jl ON jl.account_code = a.code
    LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.fiscal_year = ?
    LEFT JOIN opening_balances ob ON ob.account_code = a.code AND ob.fiscal_year = ?
    WHERE a.bs_pl = 'BS'
    GROUP BY a.code, a.name, a.category, a.subcategory, a.display_order, a.normal_balance, ob.amount
    ORDER BY a.category, a.display_order
    """
    rows = query(sql, (fy, fy))
    result = []
    for r in rows:
        opening = int(r['opening'] or 0)
        d = int(r['debit_sum'] or 0)
        c = int(r['credit_sum'] or 0)
        if r['normal_balance'] == 'debit':
            closing = opening + d - c
        else:
            closing = opening + c - d
        result.append({
            'code': r['code'], 'name': r['name'], 'category': r['category'],
            'subcategory': r['subcategory'], 'display_order': r['display_order'],
            'normal_balance': r['normal_balance'],
            'opening': opening, 'debit_sum': d, 'credit_sum': c,
            'closing': closing, 'net_income': net_income
        })
    return jsonify(result)


# ============ API: Opening balances ============
@app.route('/api/opening_balances')
def api_load_opening_balances():
    fy = int(request.args.get('fiscal_year', 2026))
    sql = """
    SELECT a.code, a.name, a.category, a.subcategory, a.normal_balance, a.display_order,
      COALESCE(ob.amount, 0) AS amount
    FROM accounts a
    LEFT JOIN opening_balances ob ON ob.account_code = a.code AND ob.fiscal_year = ?
    WHERE a.bs_pl = 'BS'
    ORDER BY a.display_order
    """
    return jsonify(query(sql, (fy,)))


@app.route('/api/opening_balances', methods=['POST'])
def api_save_opening_balance():
    d = request.get_json()
    db = get_db()
    db.execute(
        """INSERT INTO opening_balances (account_code, fiscal_year, amount, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(account_code) DO UPDATE SET amount=excluded.amount, fiscal_year=excluded.fiscal_year, updated_at=CURRENT_TIMESTAMP""",
        (d['account_code'], d['fiscal_year'], int(d['amount']))
    )
    db.commit()
    return jsonify({'ok': True})


# ============ Main ============
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print(f"\n{'='*60}")
    print(f"  青色申告 複式簿記 - ローカル版")
    print(f"  ブラウザで http://localhost:{port} を開いてください")
    print(f"  データベース: {DB_PATH}")
    print(f"  Ctrl+C で終了")
    print(f"{'='*60}\n")
    app.run(host='127.0.0.1', port=port, debug=False)