import csv
import io
import re
import secrets
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import wraps

import pymysql
import pymysql.cursors
from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

DEFAULT_CATEGORIES = [
    ("Food & Dining", "#fd7e14"), ("Transport", "#0d6efd"), ("Shopping", "#d63384"),
    ("Bills & Utilities", "#dc3545"), ("Rent", "#6f42c1"), ("Health", "#20c997"),
    ("Entertainment", "#ffc107"), ("Education", "#0dcaf0"), ("Salary", "#198754"),
    ("Other", "#6c757d"),
]
PAYMENT_METHODS = ["Cash", "UPI", "Credit Card", "Debit Card", "Net Banking", "Wallet"]
CURRENCIES = ["₹", "$", "€", "£", "¥"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------- DB
def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            host=app.config["MYSQL_HOST"], port=app.config["MYSQL_PORT"],
            user=app.config["MYSQL_USER"], password=app.config["MYSQL_PASSWORD"],
            database=app.config["MYSQL_DB"], charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        )
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, args=(), one=False):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    with get_db().cursor() as cur:
        cur.execute(sql, args)
        return cur.lastrowid


# ------------------------------------------------------------------ Security
@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or token != request.form.get("csrf_token"):
            abort(400, "Invalid or missing CSRF token. Refresh the page and try again.")


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


@app.context_processor
def inject_globals():
    return dict(csrf_token=csrf_token, currency=session.get("currency", "₹"),
                payment_methods=PAYMENT_METHODS, today=date.today())


@app.template_filter("money")
def money_filter(v):
    v = Decimal(v or 0)
    return f"{session.get('currency', '₹')}{v:,.2f}"


# ------------------------------------------------------------------- Helpers
def uid():
    return session["user_id"]


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def next_occurrence(d, freq):
    if freq == "daily":
        return d + timedelta(days=1)
    if freq == "weekly":
        return d + timedelta(weeks=1)
    if freq == "yearly":
        return add_months(d, 12)
    return add_months(d, 1)


def process_recurring(user_id):
    """Create due transactions from recurring rules (runs on each dashboard visit)."""
    rows = query("SELECT * FROM recurring WHERE user_id=%s AND active=1 AND next_date<=%s",
                 (user_id, date.today()))
    for r in rows:
        nd = r["next_date"]
        while nd <= date.today():
            execute("""INSERT INTO transactions
                       (user_id, category_id, type, amount, description, payment_method, txn_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (user_id, r["category_id"], r["type"], r["amount"],
                     r["description"] + " (recurring)", r["payment_method"], nd))
            nd = next_occurrence(nd, r["frequency"])
        execute("UPDATE recurring SET next_date=%s WHERE id=%s", (nd, r["id"]))


def seed_categories(user_id):
    for name, color in DEFAULT_CATEGORIES:
        execute("INSERT IGNORE INTO categories (user_id,name,color) VALUES (%s,%s,%s)",
                (user_id, name, color))


def user_categories():
    return query("SELECT * FROM categories WHERE user_id=%s ORDER BY name", (uid(),))


def parse_amount(raw):
    try:
        val = Decimal(raw)
    except Exception:
        return None
    return val if val > 0 else None


def parse_date(raw, default=None):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def month_bounds(d):
    return d.replace(day=1), d.replace(day=monthrange(d.year, d.month)[1])


# ---------------------------------------------------------------------- Auth
@app.route("/")
def index():
    return redirect(url_for("dashboard" if "user_id" in session else "login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        error = None
        if len(name) < 2:
            error = "Please enter your name."
        elif not EMAIL_RE.match(email):
            error = "Enter a valid email address."
        elif len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif pw != confirm:
            error = "Passwords do not match."
        elif query("SELECT id FROM users WHERE email=%s", (email,), one=True):
            error = "An account with this email already exists."
        if error:
            flash(error, "danger")
            return render_template("register.html", name=name, email=email)
        user_id = execute("INSERT INTO users (name,email,password_hash) VALUES (%s,%s,%s)",
                          (name, email, generate_password_hash(pw)))
        seed_categories(user_id)
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email=%s", (email,), one=True)
        if user and check_password_hash(user["password_hash"], pw):
            session.clear()
            session.update(user_id=user["id"], user_name=user["name"], currency=user["currency"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ----------------------------------------------------------------- Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    process_recurring(uid())
    start, end = month_bounds(date.today())

    totals = query("""SELECT
        COALESCE(SUM(CASE WHEN type='income'  THEN amount END),0) AS income,
        COALESCE(SUM(CASE WHEN type='expense' THEN amount END),0) AS expense
        FROM transactions WHERE user_id=%s AND txn_date BETWEEN %s AND %s""",
                   (uid(), start, end), one=True)
    overall = query("""SELECT
        COALESCE(SUM(CASE WHEN type='income' THEN amount ELSE -amount END),0) AS balance
        FROM transactions WHERE user_id=%s""", (uid(),), one=True)

    by_cat = query("""SELECT COALESCE(c.name,'Uncategorized') AS name, COALESCE(c.color,'#adb5bd') AS color,
        SUM(t.amount) AS total FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.user_id=%s AND t.type='expense' AND t.txn_date BETWEEN %s AND %s
        GROUP BY c.id, c.name, c.color ORDER BY total DESC""", (uid(), start, end))

    trend = []
    for i in range(5, -1, -1):
        ms, me = month_bounds(add_months(date.today().replace(day=1), -i))
        row = query("""SELECT
            COALESCE(SUM(CASE WHEN type='income'  THEN amount END),0) AS income,
            COALESCE(SUM(CASE WHEN type='expense' THEN amount END),0) AS expense
            FROM transactions WHERE user_id=%s AND txn_date BETWEEN %s AND %s""",
                    (uid(), ms, me), one=True)
        trend.append({"label": ms.strftime("%b %Y"), "income": float(row["income"]),
                      "expense": float(row["expense"])})

    budgets = query("""SELECT b.id, b.monthly_limit, c.name, c.color,
        COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.user_id=b.user_id
                  AND t.category_id=b.category_id AND t.type='expense'
                  AND t.txn_date BETWEEN %s AND %s),0) AS spent
        FROM budgets b JOIN categories c ON c.id=b.category_id WHERE b.user_id=%s""",
                    (start, end, uid()))
    for b in budgets:
        b["pct"] = round(float(b["spent"]) / float(b["monthly_limit"]) * 100, 1) if b["monthly_limit"] else 0

    recent = query("""SELECT t.*, c.name AS cat_name, c.color FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id WHERE t.user_id=%s
        ORDER BY t.txn_date DESC, t.id DESC LIMIT 6""", (uid(),))

    days_passed = date.today().day
    days_in_month = monthrange(date.today().year, date.today().month)[1]
    daily_avg = float(totals["expense"]) / days_passed if days_passed else 0
    forecast = daily_avg * days_in_month
    savings_rate = 0
    if totals["income"] > 0:
        savings_rate = round((float(totals["income"]) - float(totals["expense"])) / float(totals["income"]) * 100, 1)

    return render_template("dashboard.html", totals=totals, balance=overall["balance"],
                           by_cat=by_cat, trend=trend, budgets=budgets, recent=recent,
                           daily_avg=daily_avg, forecast=forecast, savings_rate=savings_rate,
                           month_label=start.strftime("%B %Y"))


# ------------------------------------------------------------- Transactions
def filtered_clause():
    where, args = ["t.user_id=%s"], [uid()]
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "")
    ttype = request.args.get("type", "")
    pm = request.args.get("payment", "")
    start = parse_date(request.args.get("start"))
    end = parse_date(request.args.get("end"))
    if q:
        where.append("t.description LIKE %s")
        args.append(f"%{q}%")
    if cat.isdigit():
        where.append("t.category_id=%s")
        args.append(int(cat))
    if ttype in ("expense", "income"):
        where.append("t.type=%s")
        args.append(ttype)
    if pm:
        where.append("t.payment_method=%s")
        args.append(pm)
    if start:
        where.append("t.txn_date>=%s")
        args.append(start)
    if end:
        where.append("t.txn_date<=%s")
        args.append(end)
    return " AND ".join(where), args


@app.route("/transactions")
@login_required
def transactions():
    where, args = filtered_clause()
    sort = request.args.get("sort", "date_desc")
    order = {"date_desc": "t.txn_date DESC, t.id DESC", "date_asc": "t.txn_date ASC, t.id ASC",
             "amt_desc": "t.amount DESC", "amt_asc": "t.amount ASC"}.get(sort, "t.txn_date DESC")
    page = max(int(request.args.get("page", 1) or 1), 1)
    per = app.config["PER_PAGE"]

    count = query(f"SELECT COUNT(*) AS n FROM transactions t WHERE {where}", args, one=True)["n"]
    summary = query(f"""SELECT
        COALESCE(SUM(CASE WHEN t.type='income'  THEN t.amount END),0) AS income,
        COALESCE(SUM(CASE WHEN t.type='expense' THEN t.amount END),0) AS expense
        FROM transactions t WHERE {where}""", args, one=True)
    rows = query(f"""SELECT t.*, c.name AS cat_name, c.color FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id WHERE {where}
        ORDER BY {order} LIMIT %s OFFSET %s""", args + [per, (page - 1) * per])
    pages = max((count + per - 1) // per, 1)
    qs = {k: v for k, v in request.args.items() if k != "page" and v}
    return render_template("transactions.html", rows=rows, categories=user_categories(),
                           page=page, pages=pages, count=count, summary=summary, qs=qs,
                           f=request.args)


def read_txn_form():
    f = request.form
    amount = parse_amount(f.get("amount", ""))
    d = parse_date(f.get("txn_date"))
    ttype = f.get("type", "expense")
    desc = f.get("description", "").strip()
    cat = f.get("category_id", "")
    pm = f.get("payment_method", "Cash")
    errors = []
    if not amount:
        errors.append("Enter a valid amount greater than 0.")
    if not d:
        errors.append("Enter a valid date.")
    if ttype not in ("expense", "income"):
        errors.append("Invalid type.")
    if not desc:
        errors.append("Description is required.")
    cat_id = None
    if cat.isdigit():
        if query("SELECT id FROM categories WHERE id=%s AND user_id=%s", (int(cat), uid()), one=True):
            cat_id = int(cat)
    data = dict(type=ttype, amount=amount, description=desc[:255], category_id=cat_id,
                payment_method=pm if pm in PAYMENT_METHODS else "Cash", txn_date=d)
    return data, errors


@app.route("/transactions/add", methods=["GET", "POST"])
@login_required
def add_transaction():
    if request.method == "POST":
        data, errors = read_txn_form()
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("transaction_form.html", t=request.form, categories=user_categories(), mode="Add")
        execute("""INSERT INTO transactions
            (user_id,category_id,type,amount,description,payment_method,txn_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (uid(), data["category_id"], data["type"], data["amount"], data["description"],
                 data["payment_method"], data["txn_date"]))
        flash("Transaction added.", "success")
        warn_if_over_budget(data)
        return redirect(url_for("transactions"))
    return render_template("transaction_form.html", t={"type": request.args.get("type", "expense"),
                           "txn_date": date.today().isoformat()}, categories=user_categories(), mode="Add")


def warn_if_over_budget(data):
    if data["type"] != "expense" or not data["category_id"]:
        return
    b = query("SELECT monthly_limit FROM budgets WHERE user_id=%s AND category_id=%s",
              (uid(), data["category_id"]), one=True)
    if not b:
        return
    start, end = month_bounds(data["txn_date"])
    spent = query("""SELECT COALESCE(SUM(amount),0) AS s FROM transactions
        WHERE user_id=%s AND category_id=%s AND type='expense' AND txn_date BETWEEN %s AND %s""",
                  (uid(), data["category_id"], start, end), one=True)["s"]
    if spent > b["monthly_limit"]:
        flash("Budget alert: you have exceeded the monthly budget for this category!", "warning")
    elif spent >= b["monthly_limit"] * Decimal("0.8"):
        flash("Heads up: you have used over 80% of this category's monthly budget.", "warning")


@app.route("/transactions/<int:tid>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(tid):
    t = query("SELECT * FROM transactions WHERE id=%s AND user_id=%s", (tid, uid()), one=True)
    if not t:
        abort(404)
    if request.method == "POST":
        data, errors = read_txn_form()
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("transaction_form.html", t=request.form, categories=user_categories(),
                                   mode="Edit", tid=tid)
        execute("""UPDATE transactions SET category_id=%s,type=%s,amount=%s,description=%s,
            payment_method=%s,txn_date=%s WHERE id=%s AND user_id=%s""",
                (data["category_id"], data["type"], data["amount"], data["description"],
                 data["payment_method"], data["txn_date"], tid, uid()))
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions"))
    t["txn_date"] = t["txn_date"].isoformat()
    return render_template("transaction_form.html", t=t, categories=user_categories(), mode="Edit", tid=tid)


@app.route("/transactions/<int:tid>/delete", methods=["POST"])
@login_required
def delete_transaction(tid):
    execute("DELETE FROM transactions WHERE id=%s AND user_id=%s", (tid, uid()))
    flash("Transaction deleted.", "info")
    return redirect(request.referrer or url_for("transactions"))


# ---------------------------------------------------------------- Categories
@app.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "#6c757d")
        if not name:
            flash("Category name is required.", "danger")
        elif not re.match(r"^#[0-9a-fA-F]{6}$", color):
            flash("Invalid color.", "danger")
        elif query("SELECT id FROM categories WHERE user_id=%s AND name=%s", (uid(), name), one=True):
            flash("That category already exists.", "danger")
        else:
            execute("INSERT INTO categories (user_id,name,color) VALUES (%s,%s,%s)", (uid(), name, color))
            flash("Category added.", "success")
        return redirect(url_for("categories"))
    rows = query("""SELECT c.*, (SELECT COUNT(*) FROM transactions t WHERE t.category_id=c.id) AS n
        FROM categories c WHERE c.user_id=%s ORDER BY c.name""", (uid(),))
    return render_template("categories.html", rows=rows)


@app.route("/categories/<int:cid>/delete", methods=["POST"])
@login_required
def delete_category(cid):
    execute("DELETE FROM categories WHERE id=%s AND user_id=%s", (cid, uid()))
    flash("Category deleted. Its transactions are now 'Uncategorized'.", "info")
    return redirect(url_for("categories"))


# ------------------------------------------------------------------- Budgets
@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    if request.method == "POST":
        cat = request.form.get("category_id", "")
        limit = parse_amount(request.form.get("monthly_limit", ""))
        if not cat.isdigit() or not limit:
            flash("Choose a category and enter a valid limit.", "danger")
        elif not query("SELECT id FROM categories WHERE id=%s AND user_id=%s", (int(cat), uid()), one=True):
            abort(404)
        else:
            execute("""INSERT INTO budgets (user_id,category_id,monthly_limit) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE monthly_limit=VALUES(monthly_limit)""", (uid(), int(cat), limit))
            flash("Budget saved.", "success")
        return redirect(url_for("budgets"))
    start, end = month_bounds(date.today())
    rows = query("""SELECT b.id, b.monthly_limit, c.name, c.color,
        COALESCE((SELECT SUM(t.amount) FROM transactions t WHERE t.user_id=b.user_id
                  AND t.category_id=b.category_id AND t.type='expense'
                  AND t.txn_date BETWEEN %s AND %s),0) AS spent
        FROM budgets b JOIN categories c ON c.id=b.category_id WHERE b.user_id=%s ORDER BY c.name""",
                 (start, end, uid()))
    for b in rows:
        b["pct"] = round(float(b["spent"]) / float(b["monthly_limit"]) * 100, 1)
    return render_template("budgets.html", rows=rows, categories=user_categories(),
                           month_label=start.strftime("%B %Y"))


@app.route("/budgets/<int:bid>/delete", methods=["POST"])
@login_required
def delete_budget(bid):
    execute("DELETE FROM budgets WHERE id=%s AND user_id=%s", (bid, uid()))
    flash("Budget removed.", "info")
    return redirect(url_for("budgets"))


# ----------------------------------------------------------------- Recurring
@app.route("/recurring", methods=["GET", "POST"])
@login_required
def recurring():
    if request.method == "POST":
        data, errors = read_txn_form()
        freq = request.form.get("frequency", "monthly")
        if freq not in ("daily", "weekly", "monthly", "yearly"):
            errors.append("Invalid frequency.")
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            execute("""INSERT INTO recurring
                (user_id,category_id,type,amount,description,payment_method,frequency,next_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (uid(), data["category_id"], data["type"], data["amount"], data["description"],
                     data["payment_method"], freq, data["txn_date"]))
            flash("Recurring rule created.", "success")
        return redirect(url_for("recurring"))
    rows = query("""SELECT r.*, c.name AS cat_name, c.color FROM recurring r
        LEFT JOIN categories c ON c.id=r.category_id WHERE r.user_id=%s ORDER BY r.next_date""", (uid(),))
    return render_template("recurring.html", rows=rows, categories=user_categories())


@app.route("/recurring/<int:rid>/toggle", methods=["POST"])
@login_required
def toggle_recurring(rid):
    execute("UPDATE recurring SET active = 1 - active WHERE id=%s AND user_id=%s", (rid, uid()))
    return redirect(url_for("recurring"))


@app.route("/recurring/<int:rid>/delete", methods=["POST"])
@login_required
def delete_recurring(rid):
    execute("DELETE FROM recurring WHERE id=%s AND user_id=%s", (rid, uid()))
    flash("Recurring rule deleted.", "info")
    return redirect(url_for("recurring"))


# --------------------------------------------------------------------- Goals
@app.route("/goals", methods=["GET", "POST"])
@login_required
def goals():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        target = parse_amount(request.form.get("target_amount", ""))
        deadline = parse_date(request.form.get("deadline"))
        if not name or not target:
            flash("Enter a goal name and a valid target amount.", "danger")
        else:
            execute("INSERT INTO savings_goals (user_id,name,target_amount,deadline) VALUES (%s,%s,%s,%s)",
                    (uid(), name, target, deadline))
            flash("Goal created.", "success")
        return redirect(url_for("goals"))
    rows = query("SELECT * FROM savings_goals WHERE user_id=%s ORDER BY id DESC", (uid(),))
    for g_ in rows:
        g_["pct"] = min(round(float(g_["saved_amount"]) / float(g_["target_amount"]) * 100, 1), 100)
    return render_template("goals.html", rows=rows)


@app.route("/goals/<int:gid>/contribute", methods=["POST"])
@login_required
def contribute_goal(gid):
    amt = parse_amount(request.form.get("amount", ""))
    if not amt:
        flash("Enter a valid amount.", "danger")
    else:
        execute("UPDATE savings_goals SET saved_amount = saved_amount + %s WHERE id=%s AND user_id=%s",
                (amt, gid, uid()))
        flash("Contribution added. Keep going!", "success")
    return redirect(url_for("goals"))


@app.route("/goals/<int:gid>/delete", methods=["POST"])
@login_required
def delete_goal(gid):
    execute("DELETE FROM savings_goals WHERE id=%s AND user_id=%s", (gid, uid()))
    flash("Goal deleted.", "info")
    return redirect(url_for("goals"))


# ------------------------------------------------------------------- Reports
def report_data(start, end):
    summary = query("""SELECT
        COALESCE(SUM(CASE WHEN type='income'  THEN amount END),0) AS income,
        COALESCE(SUM(CASE WHEN type='expense' THEN amount END),0) AS expense,
        COUNT(*) AS n FROM transactions WHERE user_id=%s AND txn_date BETWEEN %s AND %s""",
                    (uid(), start, end), one=True)
    by_cat = query("""SELECT COALESCE(c.name,'Uncategorized') AS name, COALESCE(c.color,'#adb5bd') AS color,
        SUM(t.amount) AS total, COUNT(*) AS n FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.user_id=%s AND t.type='expense' AND t.txn_date BETWEEN %s AND %s
        GROUP BY c.id, c.name, c.color ORDER BY total DESC""", (uid(), start, end))
    by_pm = query("""SELECT payment_method AS name, SUM(amount) AS total FROM transactions
        WHERE user_id=%s AND type='expense' AND txn_date BETWEEN %s AND %s
        GROUP BY payment_method ORDER BY total DESC""", (uid(), start, end))
    daily = query("""SELECT txn_date AS d, SUM(amount) AS total FROM transactions
        WHERE user_id=%s AND type='expense' AND txn_date BETWEEN %s AND %s
        GROUP BY txn_date ORDER BY txn_date""", (uid(), start, end))
    rows = query("""SELECT t.*, c.name AS cat_name FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.user_id=%s AND t.txn_date BETWEEN %s AND %s ORDER BY t.txn_date, t.id""",
                 (uid(), start, end))
    return summary, by_cat, by_pm, daily, rows


@app.route("/reports")
@login_required
def reports():
    ms, me = month_bounds(date.today())
    start = parse_date(request.args.get("start"), ms)
    end = parse_date(request.args.get("end"), me)
    summary, by_cat, by_pm, daily, rows = report_data(start, end)
    top = by_cat[0] if by_cat else None
    return render_template("reports.html", start=start, end=end, summary=summary, by_cat=by_cat,
                           by_pm=by_pm, daily=[{"d": r["d"].strftime("%d %b"), "total": float(r["total"])} for r in daily],
                           rows=rows, top=top)


@app.route("/reports/export/<fmt>")
@login_required
def export_report(fmt):
    ms, me = month_bounds(date.today())
    start = parse_date(request.args.get("start"), ms)
    end = parse_date(request.args.get("end"), me)
    summary, by_cat, _pm, _daily, rows = report_data(start, end)
    cur = session.get("currency", "₹")
    fname = f"expense_report_{start}_{end}"

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Date", "Type", "Category", "Description", "Payment Method", "Amount"])
        for r in rows:
            w.writerow([r["txn_date"], r["type"], r["cat_name"] or "Uncategorized",
                        r["description"], r["payment_method"], r["amount"]])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={fname}.csv"})

    if fmt == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        symbol = "Rs." if cur == "₹" else cur   # built-in PDF fonts lack the rupee glyph
        out = io.BytesIO()
        doc = SimpleDocTemplate(out, pagesize=A4, title="Expense Report")
        st = getSampleStyleSheet()
        els = [Paragraph("Expense Report", st["Title"]),
               Paragraph(f"{session['user_name']} &nbsp;|&nbsp; {start:%d %b %Y} to {end:%d %b %Y}", st["Normal"]),
               Spacer(1, 12)]
        s = Table([["Income", "Expenses", "Net"],
                   [f"{symbol}{summary['income']:,.2f}", f"{symbol}{summary['expense']:,.2f}",
                    f"{symbol}{summary['income'] - summary['expense']:,.2f}"]], hAlign="LEFT")
        s.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4f46e5")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), .5, colors.grey),
                               ("PADDING", (0, 0), (-1, -1), 8)]))
        els += [s, Spacer(1, 16), Paragraph("Spending by category", st["Heading2"])]
        ct = Table([["Category", "Txns", "Total"]] +
                   [[c["name"], c["n"], f"{symbol}{c['total']:,.2f}"] for c in by_cat], hAlign="LEFT")
        ct.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0e7ff")),
                                ("GRID", (0, 0), (-1, -1), .5, colors.lightgrey)]))
        els += [ct, Spacer(1, 16), Paragraph("Transactions", st["Heading2"])]
        data = [["Date", "Type", "Category", "Description", "Amount"]] + [
            [str(r["txn_date"]), r["type"], r["cat_name"] or "-", r["description"][:32],
             f"{symbol}{r['amount']:,.2f}"] for r in rows]
        tt = Table(data, repeatRows=1)
        tt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4f46e5")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("GRID", (0, 0), (-1, -1), .25, colors.lightgrey),
                                ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        els.append(tt)
        doc.build(els)
        return Response(out.getvalue(), mimetype="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename={fname}.pdf"})
    abort(404)


# ------------------------------------------------------------------- Profile
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = query("SELECT * FROM users WHERE id=%s", (uid(),), one=True)
    if request.method == "POST":
        action = request.form.get("action")
        if action == "details":
            name = request.form.get("name", "").strip()
            cur = request.form.get("currency", "₹")
            if len(name) < 2 or cur not in CURRENCIES:
                flash("Enter a valid name and currency.", "danger")
            else:
                execute("UPDATE users SET name=%s, currency=%s WHERE id=%s", (name, cur, uid()))
                session.update(user_name=name, currency=cur)
                flash("Profile updated.", "success")
        elif action == "password":
            old, new = request.form.get("old", ""), request.form.get("new", "")
            if not check_password_hash(user["password_hash"], old):
                flash("Current password is incorrect.", "danger")
            elif len(new) < 6:
                flash("New password must be at least 6 characters.", "danger")
            else:
                execute("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new), uid()))
                flash("Password changed.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user, currencies=CURRENCIES)


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="Page not found."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, msg=getattr(e, "description", "Bad request.")), 400


if __name__ == "__main__":
    app.run(debug=True)
