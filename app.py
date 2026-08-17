from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, date
import sqlite3
import os

# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "smart-expense-tracker-secret-key-2026"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE = os.path.join(BASE_DIR, "expenses.db")
BUDGET_FILE = os.path.join(BASE_DIR, "budget.txt")

CATEGORIES = [
    "Food",
    "Travel",
    "Shopping",
    "Bills",
    "Entertainment",
    "Health",
    "Education",
    "Other"
]


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name, column_name):
    columns = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    return any(row["name"] == column_name for row in columns)


def add_column_if_missing(conn, table_name, column_name, column_definition):
    if not column_exists(conn, table_name, column_name):
        try:
            conn.execute(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {column_definition}"
            )
        except sqlite3.OperationalError:
            pass


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    conn = get_db()

    # --------------------------------------------------------
    # USERS TABLE
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT,
            password_hash TEXT
        )
    """)

    # Older database migration
    add_column_if_missing(
        conn,
        "users",
        "password",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "users",
        "password_hash",
        "TEXT"
    )

    # --------------------------------------------------------
    # EXPENSES TABLE
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            expense_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            name TEXT
        )
    """)

    # Migration for older databases
    add_column_if_missing(
        conn,
        "expenses",
        "amount",
        "REAL"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "category",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "description",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "expense_date",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "created_at",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "user_id",
        "INTEGER"
    )

    add_column_if_missing(
        conn,
        "expenses",
        "name",
        "TEXT"
    )

    # --------------------------------------------------------
    # BUDGET TABLE
    # --------------------------------------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            amount REAL DEFAULT 0
        )
    """)

    # --------------------------------------------------------
    # DEFAULT ADMIN USER
    # --------------------------------------------------------

    admin = conn.execute(
        "SELECT * FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:

        password_hash = generate_password_hash("admin123")

        conn.execute("""
            INSERT INTO users
            (username, password, password_hash)
            VALUES (?, ?, ?)
        """, (
            "admin",
            password_hash,
            password_hash
        ))

    else:

        password_hash = generate_password_hash("admin123")

        try:
            conn.execute("""
                UPDATE users
                SET password_hash = ?
                WHERE username = 'admin'
            """, (password_hash,))
        except Exception:
            pass

        try:
            conn.execute("""
                UPDATE users
                SET password = ?
                WHERE username = 'admin'
            """, (password_hash,))
        except Exception:
            pass

    conn.commit()
    conn.close()


# ============================================================
# IMPORTANT FOR RENDER / GUNICORN
# ============================================================

# This runs when Gunicorn imports app.py.
# Therefore SQLite tables are created on Render too.

init_db()


# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required(function):

    @wraps(function)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


# ============================================================
# BUDGET FUNCTIONS
# ============================================================

def get_budget(user_id):

    conn = get_db()

    row = conn.execute(
        "SELECT amount FROM budgets WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    conn.close()

    if row:
        return float(row["amount"] or 0)

    return 0.0


def set_user_budget(user_id, amount):

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM budgets WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if existing:

        conn.execute("""
            UPDATE budgets
            SET amount = ?
            WHERE user_id = ?
        """, (
            amount,
            user_id
        ))

    else:

        conn.execute("""
            INSERT INTO budgets
            (user_id, amount)
            VALUES (?, ?)
        """, (
            user_id,
            amount
        ))

    conn.commit()
    conn.close()


# ============================================================
# DASHBOARD CALCULATIONS
# ============================================================

def calculate_dashboard(user_id):

    conn = get_db()

    expenses = conn.execute("""
        SELECT *
        FROM expenses
        WHERE user_id = ?
        ORDER BY expense_date DESC, id DESC
    """, (user_id,)).fetchall()

    # --------------------------------------------------------
    # TOTAL EXPENSE
    # --------------------------------------------------------

    total_expense = sum(
        float(row["amount"] or 0)
        for row in expenses
    )

    # --------------------------------------------------------
    # TODAY
    # --------------------------------------------------------

    today_string = date.today().strftime("%Y-%m-%d")

    today_expense = sum(
        float(row["amount"] or 0)
        for row in expenses
        if str(row["expense_date"])[:10] == today_string
    )

    # --------------------------------------------------------
    # CURRENT MONTH
    # --------------------------------------------------------

    current_month_string = datetime.now().strftime("%Y-%m")

    current_month_total = sum(
        float(row["amount"] or 0)
        for row in expenses
        if str(row["expense_date"])[:7] == current_month_string
    )

    # --------------------------------------------------------
    # PREVIOUS MONTH
    # --------------------------------------------------------

    now = datetime.now()

    if now.month == 1:
        previous_year = now.year - 1
        previous_month = 12
    else:
        previous_year = now.year
        previous_month = now.month - 1

    previous_month_string = (
        f"{previous_year:04d}-{previous_month:02d}"
    )

    previous_month_total = sum(
        float(row["amount"] or 0)
        for row in expenses
        if str(row["expense_date"])[:7] == previous_month_string
    )

    # --------------------------------------------------------
    # CHANGE
    # --------------------------------------------------------

    change_amount = (
        current_month_total - previous_month_total
    )

    if previous_month_total > 0:

        change_percentage = (
            change_amount / previous_month_total
        ) * 100

    else:

        change_percentage = 0

    # --------------------------------------------------------
    # AVERAGE
    # --------------------------------------------------------

    if expenses:

        average_expense = (
            total_expense / len(expenses)
        )

    else:

        average_expense = 0

    # --------------------------------------------------------
    # HIGHEST EXPENSE
    # --------------------------------------------------------

    highest_expense = 0
    highest_expense_name = "None"

    if expenses:

        highest_row = max(
            expenses,
            key=lambda x: float(x["amount"] or 0)
        )

        highest_expense = float(
            highest_row["amount"] or 0
        )

        highest_expense_name = (
            highest_row["description"]
            or highest_row["name"]
            or "Expense"
        )

    # --------------------------------------------------------
    # CATEGORY TOTALS
    # --------------------------------------------------------

    category_totals = {}

    for row in expenses:

        category = row["category"] or "Other"

        amount = float(row["amount"] or 0)

        category_totals[category] = (
            category_totals.get(category, 0)
            + amount
        )

    if category_totals:

        top_category = max(
            category_totals,
            key=category_totals.get
        )

        top_category_amount = category_totals[
            top_category
        ]

    else:

        top_category = "None"
        top_category_amount = 0

    # --------------------------------------------------------
    # MONTHLY DATA - LAST 6 MONTHS
    # --------------------------------------------------------

    monthly_labels = []
    monthly_totals = []

    year = now.year
    month = now.month

    for i in range(5, -1, -1):

        m = month - i
        y = year

        while m <= 0:
            m += 12
            y -= 1

        month_key = f"{y:04d}-{m:02d}"

        month_total = sum(
            float(row["amount"] or 0)
            for row in expenses
            if str(row["expense_date"])[:7] == month_key
        )

        month_name = datetime(
            y,
            m,
            1
        ).strftime("%b %Y")

        monthly_labels.append(month_name)
        monthly_totals.append(round(month_total, 2))

    # --------------------------------------------------------
    # BUDGET
    # --------------------------------------------------------

    budget_row = conn.execute(
        "SELECT amount FROM budgets WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    monthly_budget = (
        float(budget_row["amount"] or 0)
        if budget_row else 0
    )

    budget_used = current_month_total

    if monthly_budget > 0:

        budget_percentage = (
            budget_used / monthly_budget
        ) * 100

    else:

        budget_percentage = 0

    budget_remaining = (
        monthly_budget - budget_used
    )

    if monthly_budget <= 0:

        budget_status = "No Budget"

    elif budget_percentage < 70:

        budget_status = "safe"

    elif budget_percentage < 90:

        budget_status = "warning"

    else:

        budget_status = "danger"

    # --------------------------------------------------------
    # SMART INSIGHT
    # --------------------------------------------------------

    if not expenses:

        smart_insight = (
            "Start adding expenses to get smart insights."
        )

    elif top_category != "None":

        smart_insight = (
            f"Your highest spending category is "
            f"{top_category} with ₹{top_category_amount:.2f}."
        )

    else:

        smart_insight = "Keep tracking your expenses."

    # --------------------------------------------------------
    # EXPENSE ALERT
    # --------------------------------------------------------

    if change_percentage > 20:

        expense_alert = (
            "Your spending increased significantly "
            "compared with last month."
        )

    elif change_percentage < -20:

        expense_alert = (
            "Great! Your spending is lower "
            "than last month."
        )

    else:

        expense_alert = (
            "Your spending is currently stable."
        )

    conn.close()

    return {
        "expenses": expenses,
        "total_expense": round(total_expense, 2),
        "average_expense": round(average_expense, 2),
        "highest_expense": round(highest_expense, 2),
        "highest_expense_name": highest_expense_name,
        "top_category": top_category,
        "top_category_amount": round(
            top_category_amount,
            2
        ),
        "category_totals": category_totals,
        "monthly_labels": monthly_labels,
        "monthly_totals": monthly_totals,
        "today_expense": round(today_expense, 2),
        "current_month_total": round(
            current_month_total,
            2
        ),
        "previous_month_total": round(
            previous_month_total,
            2
        ),
        "change_amount": round(
            change_amount,
            2
        ),
        "change_percentage": round(
            change_percentage,
            2
        ),
        "monthly_budget": round(
            monthly_budget,
            2
        ),
        "budget_used": round(
            budget_used,
            2
        ),
        "budget_remaining": round(
            budget_remaining,
            2
        ),
        "budget_percentage": round(
            budget_percentage,
            2
        ),
        "budget_status": budget_status,
        "smart_insight": smart_insight,
        "expense_alert": expense_alert
    }


# ============================================================
# HOME / DASHBOARD
# ============================================================

@app.route("/")
@login_required
def home():

    user_id = session["user_id"]

    data = calculate_dashboard(user_id)

    return render_template(
        "index.html",
        categories=CATEGORIES,
        category_data=data["category_totals"],
        monthly_data={
            "labels": data["monthly_labels"],
            "totals": data["monthly_totals"]
        },
        **data
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = (
            request.form.get("username")
            or request.form.get("email")
            or ""
        ).strip()

        password = (
            request.form.get("password")
            or ""
        )

        if not username or not password:

            flash(
                "Please enter username and password.",
                "error"
            )

            return render_template("login.html")

        conn = get_db()

        user = conn.execute("""
            SELECT *
            FROM users
            WHERE username = ?
        """, (username,)).fetchone()

        conn.close()

        if not user:

            flash(
                "Invalid username or password.",
                "error"
            )

            return render_template("login.html")

        stored_password_hash = (
            user["password_hash"]
            or user["password"]
        )

        valid_password = False

        if stored_password_hash:

            try:

                valid_password = check_password_hash(
                    stored_password_hash,
                    password
                )

            except Exception:

                valid_password = (
                    stored_password_hash == password
                )

        if not valid_password:

            flash(
                "Invalid username or password.",
                "error"
            )

            return render_template("login.html")

        session.clear()

        session["user_id"] = user["id"]
        session["username"] = user["username"]

        return redirect(url_for("home"))

    return render_template("login.html")


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = (
            request.form.get("username")
            or request.form.get("email")
            or ""
        ).strip()

        password = (
            request.form.get("password")
            or ""
        )

        confirm_password = (
            request.form.get("confirm_password")
            or request.form.get("confirm")
            or ""
        )

        if not username or not password:

            flash(
                "Username and password are required.",
                "error"
            )

            return render_template("register.html")

        if len(password) < 4:

            flash(
                "Password must contain at least 4 characters.",
                "error"
            )

            return render_template("register.html")

        if confirm_password and password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return render_template("register.html")

        password_hash = generate_password_hash(password)

        conn = get_db()

        try:

            conn.execute("""
                INSERT INTO users
                (username, password, password_hash)
                VALUES (?, ?, ?)
            """, (
                username,
                password_hash,
                password_hash
            ))

            conn.commit()

            flash(
                "Registration successful. Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            flash(
                "Username already exists.",
                "error"
            )

            return render_template("register.html")

        finally:

            conn.close()

    return render_template("register.html")


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# ============================================================
# ADD EXPENSE
# ============================================================

@app.route("/add", methods=["POST"])
@login_required
def add():

    return add_expense()


@app.route("/add_expense", methods=["POST"])
@login_required
def add_expense():

    amount_raw = (
        request.form.get("amount")
        or "0"
    ).strip()

    category = (
        request.form.get("category")
        or "Other"
    ).strip()

    description = (
        request.form.get("description")
        or request.form.get("name")
        or ""
    ).strip()

    expense_date = (
        request.form.get("expense_date")
        or request.form.get("date")
        or date.today().strftime("%Y-%m-%d")
    ).strip()

    try:

        amount = float(amount_raw)

    except ValueError:

        flash(
            "Please enter a valid amount.",
            "error"
        )

        return redirect(url_for("home"))

    if amount <= 0:

        flash(
            "Amount must be greater than zero.",
            "error"
        )

        return redirect(url_for("home"))

    if category not in CATEGORIES:

        category = "Other"

    conn = get_db()

    conn.execute("""
        INSERT INTO expenses
        (
            amount,
            category,
            description,
            expense_date,
            created_at,
            user_id,
            name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        amount,
        category,
        description,
        expense_date,
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        session["user_id"],
        description
    ))

    conn.commit()
    conn.close()

    flash(
        "Expense added successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# DELETE EXPENSE
# ============================================================

@app.route("/delete/<int:expense_id>")
@login_required
def delete_expense(expense_id):

    conn = get_db()

    conn.execute("""
        DELETE FROM expenses
        WHERE id = ?
        AND user_id = ?
    """, (
        expense_id,
        session["user_id"]
    ))

    conn.commit()
    conn.close()

    flash(
        "Expense deleted successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# EDIT EXPENSE - GET
# ============================================================

@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):

    conn = get_db()

    expense = conn.execute("""
        SELECT *
        FROM expenses
        WHERE id = ?
        AND user_id = ?
    """, (
        expense_id,
        session["user_id"]
    )).fetchone()

    if not expense:

        conn.close()

        flash(
            "Expense not found.",
            "error"
        )

        return redirect(url_for("home"))

    if request.method == "POST":

        amount_raw = (
            request.form.get("amount")
            or "0"
        ).strip()

        category = (
            request.form.get("category")
            or "Other"
        ).strip()

        description = (
            request.form.get("description")
            or request.form.get("name")
            or ""
        ).strip()

        expense_date = (
            request.form.get("expense_date")
            or date.today().strftime("%Y-%m-%d")
        ).strip()

        try:

            amount = float(amount_raw)

        except ValueError:

            conn.close()

            flash(
                "Invalid amount.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_expense",
                    expense_id=expense_id
                )
            )

        if category not in CATEGORIES:

            category = "Other"

        conn.execute("""
            UPDATE expenses
            SET
                amount = ?,
                category = ?,
                description = ?,
                name = ?,
                expense_date = ?
            WHERE id = ?
            AND user_id = ?
        """, (
            amount,
            category,
            description,
            description,
            expense_date,
            expense_id,
            session["user_id"]
        ))

        conn.commit()
        conn.close()

        flash(
            "Expense updated successfully.",
            "success"
        )

        return redirect(url_for("home"))

    conn.close()

    return render_template(
        "edit_expense.html",
        expense=expense,
        categories=CATEGORIES
    )


# ============================================================
# ALTERNATIVE EDIT ROUTE
# ============================================================

@app.route("/edit_expense/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense_alt(expense_id):

    return edit_expense(expense_id)


# ============================================================
# SET BUDGET
# ============================================================

@app.route("/set-budget", methods=["POST"])
@login_required
def set_budget():

    amount_raw = (
        request.form.get("budget")
        or request.form.get("amount")
        or "0"
    ).strip()

    try:

        amount = float(amount_raw)

    except ValueError:

        flash(
            "Please enter a valid budget.",
            "error"
        )

        return redirect(url_for("home"))

    if amount < 0:

        flash(
            "Budget cannot be negative.",
            "error"
        )

        return redirect(url_for("home"))

    set_user_budget(
        session["user_id"],
        amount
    )

    # Also keep budget.txt for local compatibility
    try:

        with open(
            BUDGET_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(str(amount))

    except Exception:
        pass

    flash(
        "Monthly budget updated successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# SEARCH
# ============================================================

@app.route("/search")
@login_required
def search():

    query = (
        request.args.get("q")
        or request.args.get("search")
        or ""
    ).strip()

    conn = get_db()

    if query:

        expenses = conn.execute("""
            SELECT *
            FROM expenses
            WHERE user_id = ?
            AND (
                description LIKE ?
                OR name LIKE ?
                OR category LIKE ?
            )
            ORDER BY expense_date DESC, id DESC
        """, (
            session["user_id"],
            f"%{query}%",
            f"%{query}%",
            f"%{query}%"
        )).fetchall()

    else:

        expenses = conn.execute("""
            SELECT *
            FROM expenses
            WHERE user_id = ?
            ORDER BY expense_date DESC, id DESC
        """, (
            session["user_id"],
        )).fetchall()

    conn.close()

    data = calculate_dashboard(
        session["user_id"]
    )

    return render_template(
        "index.html",
        categories=CATEGORIES,
        expenses=expenses,
        search_query=query,
        category_data=data["category_totals"],
        monthly_data={
            "labels": data["monthly_labels"],
            "totals": data["monthly_totals"]
        },
        **{
            key: value
            for key, value in data.items()
            if key != "expenses"
        }
    )


# ============================================================
# HEALTH CHECK FOR RENDER
# ============================================================

@app.route("/health")
def health():

    try:

        conn = get_db()

        conn.execute(
            "SELECT 1"
        ).fetchone()

        conn.close()

        return {
            "status": "ok",
            "database": "connected"
        }

    except Exception as error:

        return {
            "status": "error",
            "message": str(error)
        }, 500


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    print()
    print("==========================================")
    print("       SMART EXPENSE TRACKER")
    print("==========================================")
    print()

    print("Default Admin Login:")
    print("Username: admin")
    print("Password: admin123")
    print()

    print("Register:")
    print("http://127.0.0.1:5000/register")
    print()

    print("Login:")
    print("http://127.0.0.1:5000/login")
    print()

    print("Dashboard:")
    print("http://127.0.0.1:5000/")
    print()

    print("Health:")
    print("http://127.0.0.1:5000/health")
    print()

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get("PORT", 5000)
        ),
        debug=True
    )