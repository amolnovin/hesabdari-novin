-- =====================================================================
--  مرحله ۲) شمای پایگاه داده — حسابداری کسب‌وکار کوچک
--  مشتریان + انبار + فاکتور + گزارشات      (SQLite)
-- ---------------------------------------------------------------------
--  قوانین حیاتی که در سطح پایگاه داده اجرا می‌شوند (نه فقط در رابط کاربری):
--    * هیچ سندی بدون تراز بودن قطعی نمی‌شود
--    * سند قطعی‌شده هرگز ویرایش یا حذف نمی‌شود (فقط سند اصلاحی)
--    * مبالغ فقط عدد صحیح (ریال) — استفاده از float ممنوع
-- =====================================================================

PRAGMA foreign_keys = ON;
PRAGMA user_version = 2;

-- ---------------------------------------------------------------------
-- تنظیمات عمومی (نرخ مالیات، مشخصات شرکت، واحد نمایش پول)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT OR IGNORE INTO settings(key, value) VALUES
    ('company_name',   'کسب‌وکار من'),
    ('company_national_id', ''),
    ('company_economic_code', ''),
    ('company_address', ''),
    ('company_phone',  ''),
    ('default_vat_rate', '10'),      -- درصد
    ('money_unit',     'rial'),      -- rial | toman
    ('invoice_footer', 'با تشکر از خرید شما');

-- ---------------------------------------------------------------------
-- سال مالی
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fiscal_year (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date   TEXT NOT NULL,
    is_closed  INTEGER NOT NULL DEFAULT 0 CHECK (is_closed IN (0,1)),
    UNIQUE (start_date, end_date),
    CHECK (start_date < end_date)
);

-- ---------------------------------------------------------------------
-- درخت حساب‌ها (کدینگ)
--   type: asset | liability | equity | revenue | expense
--   is_postable = 1  یعنی می‌توان روی آن سند زد (حساب‌های گروه = ۰)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES accounts(id) ON DELETE RESTRICT,
    type        TEXT NOT NULL CHECK (type IN
                    ('asset','liability','equity','revenue','expense')),
    level       INTEGER NOT NULL DEFAULT 1,
    is_postable INTEGER NOT NULL DEFAULT 1 CHECK (is_postable IN (0,1)),
    has_party   INTEGER NOT NULL DEFAULT 0 CHECK (has_party   IN (0,1)),
    is_system   INTEGER NOT NULL DEFAULT 0 CHECK (is_system   IN (0,1)),
    CHECK (is_postable = 0 OR parent_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS ix_accounts_parent ON accounts(parent_id);
CREATE INDEX IF NOT EXISTS ix_accounts_type   ON accounts(type);

-- ---------------------------------------------------------------------
-- مشتریان و تامین‌کنندگان
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parties (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT UNIQUE,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'customer'
                  CHECK (kind IN ('customer','supplier','both')),
    phone         TEXT,
    address       TEXT,
    national_id   TEXT,
    economic_code TEXT,
    postal_code   TEXT,
    credit_limit  INTEGER NOT NULL DEFAULT 0,
    opening_balance INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    note          TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_parties_name ON parties(name);

-- ---------------------------------------------------------------------
-- کالاها و خدمات
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS items (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT UNIQUE,
    name           TEXT NOT NULL,
    unit           TEXT NOT NULL DEFAULT 'عدد',
    sale_price     INTEGER NOT NULL DEFAULT 0,   -- ریال
    purchase_price INTEGER NOT NULL DEFAULT 0,   -- ریال
    vat_rate       REAL    NOT NULL DEFAULT 0,   -- درصد
    track_stock    INTEGER NOT NULL DEFAULT 1 CHECK (track_stock IN (0,1)),
    stock_min      REAL    NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_items_name ON items(name);

-- ---------------------------------------------------------------------
-- گردش انبار (موجودی هیچ‌گاه به صورت عددِ جداگانه ذخیره نمی‌شود؛
-- همیشه از مجموعِ این حرکت‌ها محاسبه می‌گردد ← دقت و حسابرسی‌پذیری)
--   qty: مثبت = ورود به انبار، منفی = خروج از انبار
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stock_moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    move_date   TEXT    NOT NULL,                 -- ISO
    qty         REAL    NOT NULL,                 -- علامت‌دار
    unit_cost   INTEGER NOT NULL DEFAULT 0,       -- ریال (میانگین موزون در لحظهٔ حرکت)
    value       INTEGER NOT NULL DEFAULT 0,       -- ارزش کل حرکت به ریال (علامت‌دار، دقیق)
    move_type   TEXT    NOT NULL CHECK (move_type IN
                    ('opening','purchase','sale','sale_return',
                     'purchase_return','adjust')),
    ref_type    TEXT,
    ref_id      INTEGER,
    description TEXT
);
CREATE INDEX IF NOT EXISTS ix_moves_item ON stock_moves(item_id, move_date);
CREATE INDEX IF NOT EXISTS ix_moves_ref  ON stock_moves(ref_type, ref_id);

-- ---------------------------------------------------------------------
-- فاکتورها
--   kind  : sale | sale_return | purchase | purchase_return
--   status: draft | confirmed | cancelled
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    no              INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN
                    ('sale','sale_return','purchase','purchase_return')),
    party_id        INTEGER NOT NULL REFERENCES parties(id),
    fiscal_year_id  INTEGER NOT NULL REFERENCES fiscal_year(id),
    inv_date        TEXT NOT NULL,                -- ISO
    jalali_date     TEXT NOT NULL,
    due_date        TEXT,
    subtotal        INTEGER NOT NULL DEFAULT 0,
    discount        INTEGER NOT NULL DEFAULT 0,
    vat_amount      INTEGER NOT NULL DEFAULT 0,
    total           INTEGER NOT NULL DEFAULT 0,
    paid_amount     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','confirmed','cancelled')),
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    description     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    cogs_amount     INTEGER NOT NULL DEFAULT 0,
    stock_amount    INTEGER NOT NULL DEFAULT 0,
    expense_amount  INTEGER NOT NULL DEFAULT 0,
    UNIQUE (kind, fiscal_year_id, no)
);
CREATE INDEX IF NOT EXISTS ix_inv_party ON invoices(party_id);
CREATE INDEX IF NOT EXISTS ix_inv_date  ON invoices(inv_date);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id  INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item_id     INTEGER REFERENCES items(id),
    description TEXT,
    qty         REAL    NOT NULL DEFAULT 1,
    unit_price  INTEGER NOT NULL DEFAULT 0,       -- ریال
    discount    INTEGER NOT NULL DEFAULT 0,       -- ریال
    vat_rate    REAL    NOT NULL DEFAULT 0,
    line_total  INTEGER NOT NULL DEFAULT 0,       -- ریال (قبل از مالیات)
    unit_cost   INTEGER NOT NULL DEFAULT 0        -- بهای تمام‌شده در لحظهٔ فروش
);
CREATE INDEX IF NOT EXISTS ix_invlines_inv ON invoice_lines(invoice_id);

-- ---------------------------------------------------------------------
-- دریافت و پرداخت
--   direction: receipt (دریافت از مشتری) | payment (پرداخت به تامین‌کننده)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    no               INTEGER NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('receipt','payment')),
    method           TEXT NOT NULL DEFAULT 'cash'
                     CHECK (method IN ('cash','bank','pos','transfer')),
    party_id         INTEGER NOT NULL REFERENCES parties(id),
    amount           INTEGER NOT NULL CHECK (amount > 0),
    pay_date         TEXT NOT NULL,
    jalali_date      TEXT NOT NULL,
    invoice_id       INTEGER REFERENCES invoices(id),
    is_cancelled     INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0,1)),
    description      TEXT,
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_pay_party ON payments(party_id);

-- ---------------------------------------------------------------------
-- اسناد حسابداری (هستهٔ سیستم)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_entries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    no             INTEGER NOT NULL,
    fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_year(id),
    entry_date     TEXT NOT NULL,
    jalali_date    TEXT NOT NULL,
    entry_type     TEXT NOT NULL DEFAULT 'general' CHECK (entry_type IN
                    ('opening','general','sale','sale_return','purchase',
                     'purchase_return','receipt','payment','adjustment','closing')),
    reference_no   TEXT,
    description    TEXT,
    status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft','posted')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    posted_at      TEXT,
    created_by     INTEGER REFERENCES users(id),
    posted_by      INTEGER REFERENCES users(id),
    reversed_entry_id INTEGER REFERENCES journal_entries(id),
    UNIQUE (fiscal_year_id, no)
);
CREATE INDEX IF NOT EXISTS ix_je_date ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS ix_je_type ON journal_entries(entry_type);

CREATE TABLE IF NOT EXISTS journal_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    line_no     INTEGER NOT NULL DEFAULT 1,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    party_id    INTEGER REFERENCES parties(id) ON DELETE RESTRICT,
    debit       INTEGER NOT NULL DEFAULT 0 CHECK (debit  >= 0),   -- ریال
    credit      INTEGER NOT NULL DEFAULT 0 CHECK (credit >= 0),   -- ریال
    description TEXT,
    CHECK (debit > 0 OR credit > 0),
    CHECK (debit = 0 OR credit = 0),
    UNIQUE (entry_id, line_no)
);
CREATE INDEX IF NOT EXISTS ix_jl_entry   ON journal_lines(entry_id);
CREATE INDEX IF NOT EXISTS ix_jl_account ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS ix_jl_party   ON journal_lines(party_id);

-- ---------------------------------------------------------------------
-- شماره‌گذاری خودکار و لاگ
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sequences (
    name       TEXT NOT NULL,
    year       TEXT NOT NULL DEFAULT '',
    last_value INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (name, year)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (datetime('now')),
    action     TEXT NOT NULL,
    table_name TEXT,
    record_id  INTEGER,
    detail     TEXT,
    user_id    INTEGER,
    username   TEXT,
    role       TEXT,
    before_json TEXT,
    after_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);

-- =====================================================================
--  تریگرهای حیاتی (اجرای قوانین در سطح پایگاه داده)
-- =====================================================================
CREATE TRIGGER IF NOT EXISTS trg_lines_no_edit_posted
BEFORE UPDATE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries e
             WHERE e.id = OLD.entry_id AND e.status = 'posted')
BEGIN
    SELECT RAISE(ABORT, 'سند قطعی‌شده قابل ویرایش نیست؛ از سند اصلاحی استفاده کنید');
END;

CREATE TRIGGER IF NOT EXISTS trg_lines_no_delete_posted
BEFORE DELETE ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries e
             WHERE e.id = OLD.entry_id AND e.status = 'posted')
BEGIN
    SELECT RAISE(ABORT, 'سطر سند قطعی‌شده قابل حذف نیست');
END;

CREATE TRIGGER IF NOT EXISTS trg_lines_no_insert_posted
BEFORE INSERT ON journal_lines
WHEN EXISTS (SELECT 1 FROM journal_entries e
             WHERE e.id = NEW.entry_id AND e.status = 'posted')
BEGIN
    SELECT RAISE(ABORT, 'افزودن سطر به سند قطعی‌شده مجاز نیست');
END;

CREATE TRIGGER IF NOT EXISTS trg_entry_no_update_posted
BEFORE UPDATE ON journal_entries
WHEN OLD.status = 'posted'
BEGIN
    SELECT RAISE(ABORT, 'سند قطعی‌شده تغییرناپذیر است؛ فقط سند اصلاحی/معکوس ثبت کنید');
END;

CREATE TRIGGER IF NOT EXISTS trg_entry_no_delete_posted
BEFORE DELETE ON journal_entries
WHEN OLD.status = 'posted'
BEGIN
    SELECT RAISE(ABORT, 'حذف سند قطعی‌شده مجاز نیست؛ از سند معکوس استفاده کنید');
END;

CREATE TRIGGER IF NOT EXISTS trg_entry_no_direct_posted
BEFORE INSERT ON journal_entries
WHEN NEW.status = 'posted'
BEGIN
    SELECT RAISE(ABORT, 'سند باید ابتدا پیش‌نویس ایجاد و سپس قطعی شود');
END;

CREATE TRIGGER IF NOT EXISTS trg_entry_must_balance
BEFORE UPDATE OF status ON journal_entries
WHEN NEW.status = 'posted' AND OLD.status <> 'posted'
BEGIN
    SELECT RAISE(ABORT, 'سند تراز نیست: جمع بدهکار و بستانکار برابر نیست')
    WHERE (SELECT COALESCE(SUM(debit),0)  FROM journal_lines WHERE entry_id = NEW.id)
       <> (SELECT COALESCE(SUM(credit),0) FROM journal_lines WHERE entry_id = NEW.id)
       OR (SELECT COUNT(*) FROM journal_lines WHERE entry_id = NEW.id) < 2;
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_no_edit_confirmed
BEFORE UPDATE ON invoices
WHEN OLD.status <> 'draft' AND (
     NEW.party_id IS NOT OLD.party_id OR NEW.kind IS NOT OLD.kind OR
     NEW.inv_date IS NOT OLD.inv_date OR NEW.subtotal IS NOT OLD.subtotal OR
     NEW.discount IS NOT OLD.discount OR NEW.vat_amount IS NOT OLD.vat_amount OR
     NEW.total IS NOT OLD.total OR NEW.fiscal_year_id IS NOT OLD.fiscal_year_id)
BEGIN
    SELECT RAISE(ABORT, 'فاکتور قطعی/ابطال‌شده قابل ویرایش نیست');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_no_delete_confirmed
BEFORE DELETE ON invoices
WHEN OLD.status <> 'draft'
BEGIN
    SELECT RAISE(ABORT, 'حذف فاکتور قطعی/ابطال‌شده مجاز نیست');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_lines_no_edit_confirmed
BEFORE UPDATE ON invoice_lines
WHEN EXISTS (SELECT 1 FROM invoices i WHERE i.id = OLD.invoice_id AND i.status <> 'draft')
BEGIN
    SELECT RAISE(ABORT, 'سطر فاکتور قطعی‌شده قابل ویرایش نیست');
END;

CREATE TRIGGER IF NOT EXISTS trg_invoice_lines_no_delete_confirmed
BEFORE DELETE ON invoice_lines
WHEN EXISTS (SELECT 1 FROM invoices i WHERE i.id = OLD.invoice_id AND i.status <> 'draft')
BEGIN
    SELECT RAISE(ABORT, 'سطر فاکتور قطعی‌شده قابل حذف نیست');
END;

-- =====================================================================
--  نماهای گزارش‌گیری
-- =====================================================================
CREATE VIEW IF NOT EXISTS v_trial_balance AS
SELECT a.code, a.name, a.type,
       COALESCE(SUM(CASE WHEN e.status='posted' THEN l.debit  END),0) AS debit,
       COALESCE(SUM(CASE WHEN e.status='posted' THEN l.credit END),0) AS credit,
       COALESCE(SUM(CASE WHEN e.status='posted' THEN l.debit  END),0)
     - COALESCE(SUM(CASE WHEN e.status='posted' THEN l.credit END),0) AS balance
FROM accounts a
LEFT JOIN journal_lines   l ON l.account_id = a.id
LEFT JOIN journal_entries e ON e.id = l.entry_id
WHERE a.is_postable = 1
GROUP BY a.id
ORDER BY a.code;

DROP VIEW IF EXISTS v_party_balance;
CREATE VIEW v_party_balance AS
SELECT p.id AS party_id, p.code, p.name, p.kind,
       COALESCE(SUM(CASE WHEN a.type IN ('asset','expense')
                         THEN l.debit - l.credit
                         ELSE l.credit - l.debit END), 0) AS balance
FROM parties p
LEFT JOIN journal_lines   l ON l.party_id = p.id
LEFT JOIN accounts        a ON a.id = l.account_id AND a.has_party = 1
LEFT JOIN journal_entries e ON e.id = l.entry_id
WHERE l.id IS NULL                       -- شخصِ بدون سند
   OR (a.id IS NOT NULL                  -- فقط حساب‌های معین‌دار لحاظ می‌شوند
       AND e.status = 'posted')          -- فقط اسناد قطعی
GROUP BY p.id;

CREATE VIEW IF NOT EXISTS v_general_ledger AS
SELECT e.id AS entry_id, e.no AS entry_no, e.entry_date, e.jalali_date,
       e.entry_type, e.reference_no, e.status, e.description AS entry_desc,
       l.account_id, a.code AS account_code, a.name AS account_name,
       l.party_id, l.debit, l.credit, l.description
FROM journal_entries e
JOIN journal_lines   l ON l.entry_id = e.id
JOIN accounts        a ON a.id = l.account_id;

CREATE VIEW IF NOT EXISTS v_stock_balance AS
SELECT i.id AS item_id, i.code, i.name, i.unit, i.stock_min,
       COALESCE(SUM(m.qty), 0) AS qty
FROM items i
LEFT JOIN stock_moves m ON m.item_id = i.id
WHERE i.track_stock = 1
GROUP BY i.id;

-- =====================================================================
--  کدینگ پیش‌فرض (سرفصل‌های استاندارد یک کسب‌وکار کوچک)
--  حساب‌های is_system=1 ستون‌های برنامه هستند و نباید حذف شوند
-- =====================================================================
INSERT OR IGNORE INTO accounts (id, code, name, parent_id, type, level, is_postable, has_party, is_system) VALUES
 (1,  '1',     'دارایی‌ها',                    NULL, 'asset',     1, 0, 0, 1),
 (2,  '101',   'دارایی‌های جاری',              1,    'asset',     2, 0, 0, 1),
 (3,  '10101', 'صندوق',                        2,    'asset',     3, 1, 0, 1),
 (4,  '10102', 'بانک',                         2,    'asset',     3, 1, 0, 1),
 (5,  '10103', 'مشتریان (حساب‌های دریافتنی)',   2,    'asset',     3, 1, 1, 1),
 (6,  '10104', 'اسناد دریافتنی',                2,    'asset',     3, 1, 0, 1),
 (7,  '10105', 'موجودی کالا',                  2,    'asset',     3, 1, 0, 1),
 (8,  '10106', 'اعتبار مالیاتی خرید',           2,    'asset',     3, 1, 0, 1),
 (9,  '2',     'بدهی‌ها',                      NULL, 'liability', 1, 0, 0, 1),
 (10, '201',   'بدهی‌های جاری',                 9,    'liability', 2, 0, 0, 1),
 (11, '20101', 'تامین‌کنندگان (حساب‌های پرداختنی)', 10, 'liability', 3, 1, 1, 1),
 (12, '20102', 'اسناد پرداختنی',                10,   'liability', 3, 1, 0, 1),
 (13, '20103', 'مالیات بر ارزش افزوده پرداختنی',10,   'liability', 3, 1, 0, 1),
 (14, '3',     'حقوق صاحبان سهام',             NULL, 'equity',    1, 0, 0, 1),
 (15, '301',   'سرمایه',                       14,   'equity',    2, 1, 0, 1),
 (16, '302',   'سود و زیان انباشته',            14,   'equity',    2, 1, 0, 1),
 (17, '4',     'درآمدها',                      NULL, 'revenue',   1, 0, 0, 1),
 (18, '401',   'فروش کالا',                    17,   'revenue',   2, 1, 0, 1),
 (19, '402',   'درآمد خدمات',                  17,   'revenue',   2, 1, 0, 1),
 (20, '403',   'برگشت از فروش و تخفیفات',       17,   'revenue',   2, 1, 0, 1),
 (21, '5',     'هزینه‌ها',                     NULL, 'expense',   1, 0, 0, 1),
 (22, '501',   'بهای تمام‌شده کالای فروخته‌شده', 21,  'expense',   2, 1, 0, 1),
 (23, '502',   'هزینه‌های اداری و عمومی',       21,   'expense',   2, 1, 0, 1),
 (24, '503',   'هزینه حقوق و دستمزد',           21,   'expense',   2, 1, 0, 1),
 (25, '504',   'هزینه حمل و نقل',               21,   'expense',   2, 1, 0, 1),
 (26, '505',   'تعدیلات و ضایعات انبار',          21,   'expense',   2, 1, 0, 1);

-- =====================================================================
--  بخش دومِ شِما (افزوده‌شده در مرحلهٔ ۹)
--  کاربران و دسترسی • چک‌ها • قفل دوره مالی
-- =====================================================================

-- ---------------------------------------------------------------------
-- کاربران و سطوح دسترسی
--   role: admin | accountant | operator | viewer
--   رمز عبور فقط به صورت «هش + نمک» ذخیره می‌شود (PBKDF2)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    full_name     TEXT,
    role          TEXT NOT NULL DEFAULT 'operator'
                  CHECK (role IN ('admin','accountant','operator','viewer')),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    last_login_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- چک‌های دریافتنی و پرداختنی
--   cheque_type : received (دریافتنی از مشتری) | paid (پرداختنی به تامین‌کننده)
--   status      : pending | cleared | bounced | cancelled
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cheques (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cheque_type      TEXT NOT NULL CHECK (cheque_type IN ('received','paid')),
    serial_no        TEXT NOT NULL,
    bank_name        TEXT,
    branch           TEXT,
    amount           INTEGER NOT NULL CHECK (amount > 0),   -- ریال
    issue_date       TEXT NOT NULL,                          -- ISO
    due_date         TEXT NOT NULL,                          -- ISO
    jalali_issue     TEXT,
    jalali_due       TEXT,
    party_id         INTEGER NOT NULL REFERENCES parties(id),
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','cleared','bounced','cancelled')),
    sayad_id         TEXT,                                   -- شناسه صیاد
    description      TEXT,
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    cleared_entry_id INTEGER REFERENCES journal_entries(id),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (cheque_type, serial_no)
);
CREATE INDEX IF NOT EXISTS ix_chq_due    ON cheques(due_date);
CREATE INDEX IF NOT EXISTS ix_chq_status ON cheques(status);

-- ---------------------------------------------------------------------
-- قفل دوره مالی (۱..۱۲ = ماه‌های شمسی)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS period_lock (
    fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_year(id) ON DELETE CASCADE,
    period_no      INTEGER NOT NULL CHECK (period_no BETWEEN 1 AND 12),
    is_locked      INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0,1)),
    locked_at      TEXT,
    PRIMARY KEY (fiscal_year_id, period_no)
);

-- تنظیماتِ جدید
INSERT OR IGNORE INTO settings(key, value) VALUES
    ('auto_backup',   '1'),      -- پشتیبان خودکار هنگام خروج
    ('backup_keep',   '10'),     -- تعداد نسخه‌های نگهداری‌شده
    ('default_term_days', '30'); -- مهلت پیش‌فرض پرداخت فاکتور (برای سنوات بدهی)
