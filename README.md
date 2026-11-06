# SpendWise – Personal Expense Tracker

Flask + MySQL + Bootstrap 5 web app for tracking income and expenses.

## Features

**Core (project requirements)**
1. User registration (validated, passwords hashed)
2. Login / logout (session based)
3. Add records (expenses and income)
4. View records (paginated table)
5. Update records
6. Delete records (with confirmation)
7. Search & filter (text, category, type, payment method, date range, sorting)
8. Data storage in **MySQL**
9. Dashboard (totals, trend chart, category chart, recent transactions)
10. Report generation (date-range report, **CSV** and **PDF** export, print)

**Advanced extras**
- Monthly **budgets** per category with progress bars and 80% / 100% alerts
- **Recurring transactions** (rent, salary, subscriptions) auto-added when due
- **Savings goals** with contributions and progress
- Smart insights: savings rate, daily average, projected month-end spend
- Custom categories with colours
- Multi-currency symbol (₹ $ € £ ¥) and profile / password change
- Dark mode, responsive sidebar UI, Chart.js charts
- CSRF protection on all forms, per-user data isolation, parameterised SQL

## Setup

1. Install Python 3.10+ and MySQL 8.
2. Create the database and tables:
   ```
   mysql -u root -p < schema.sql
   ```
3. Set your MySQL password in `config.py` (`MYSQL_PASSWORD`) or via environment variable.
4. Install dependencies and run:
   ```
   python -m venv venv
   venv\Scripts\activate        # Windows   (Linux/Mac: source venv/bin/activate)
   pip install -r requirements.txt
   python app.py
   ```
5. Open http://127.0.0.1:5000 in Chrome, register an account and start tracking.

## Project structure

```
expense_tracker/
├── app.py            # routes + logic
├── config.py         # DB settings
├── schema.sql        # MySQL tables
├── requirements.txt
├── static/css, static/js
└── templates/        # Jinja2 + Bootstrap pages
```

## Database tables
`users`, `categories`, `transactions`, `budgets`, `recurring`, `savings_goals`
