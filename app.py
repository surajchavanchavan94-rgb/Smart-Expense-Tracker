from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import sqlite3
import os
from datetime import datetime, date

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "smart-expense-tracker-secret-key-2026"
)

# ============================================================
# DATABASE
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Render वर writable location
if os.environ.get("RENDER"):
    DATABASE = "/tmp/expenses.db"
else:
    DATABASE = os.path.join(BASE_DIR, "expenses.db")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    # USERS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # EXPENSES
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            expense_date TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # BUDGETS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            amount REAL DEFAULT 0
        )
    """)

    # DEFAULT ADMIN
    admin = conn.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if not admin:
        password_hash = generate_password_hash("admin123")

        conn.execute(
            """
            INSERT INTO users (username, password)
            VALUES (?, ?)
            """,
            ("admin", password_hash)
        )

    conn.commit()
    conn.close()


# IMPORTANT:
# Gunicorn/Render import करताना database तयार होईल.
init_db()


# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            return redirect(url_for("login"))

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# DASHBOARD CALCULATIONS
# ============================================================

def get_dashboard_data(user_id):

    conn = get_db()

    expenses = conn.execute(
        """
        SELECT *
        FROM expenses
        WHERE user_id = ?
        ORDER BY expense_date DESC, id DESC
        """,
        (user_id,)
    ).fetchall()

    # TOTAL
    total_expense = sum(float(row["amount"]) for row in expenses)

    # CURRENT MONTH
    today = date.today()

    current_month = today.strftime("%Y-%m")
    previous_month = (
        today.replace(day=1).toordinal() - 1
    )

    previous_date = date.fromordinal(previous_month)

    previous_month_key = previous_date.strftime("%Y-%m")

    current_month_total = sum(
        float(row["amount"])
        for row in expenses
        if row["expense_date"].startswith(current_month)
    )

    previous_month_total = sum(
        float(row["amount"])
        for row in expenses
        if row["expense_date"].startswith(previous_month_key)
    )

    # TODAY
    today_key = today.strftime("%Y-%m-%d")

    today_total = sum(
        float(row["amount"])
        for row in expenses
        if row["expense_date"] == today_key
    )

    # AVERAGE
    if expenses:
        average_expense = total_expense / len(expenses)
    else:
        average_expense = 0

    # HIGHEST
    if expenses:

        highest_row = max(
            expenses,
            key=lambda x: float(x["amount"])
        )

        highest_expense = float(highest_row["amount"])
        highest_expense_name = highest_row["name"]

    else:

        highest_expense = 0
        highest_expense_name = "None"

    # CATEGORY TOTALS
    category_totals = {}

    for row in expenses:

        category = row["category"]

        category_totals[category] = (
            category_totals.get(category, 0)
            + float(row["amount"])
        )

    if category_totals:

        top_category = max(
            category_totals,
            key=category_totals.get
        )

        top_category_amount = category_totals[top_category]

    else:

        top_category = "None"
        top_category_amount = 0

    # MONTHLY TOTALS
    monthly_totals_dict = {}

    for row in expenses:

        month = row["expense_date"][:7]

        monthly_totals_dict[month] = (
            monthly_totals_dict.get(month, 0)
            + float(row["amount"])
        )

    sorted_months = sorted(monthly_totals_dict.keys())

    monthly_labels = sorted_months[-12:]

    monthly_totals = [
        monthly_totals_dict[m]
        for m in monthly_labels
    ]

    # CHANGE
    change_amount = current_month_total - previous_month_total

    if previous_month_total > 0:

        change_percentage = (
            change_amount / previous_month_total
        ) * 100

    else:

        change_percentage = 0

    # INSIGHT
    if total_expense == 0:

        smart_insight = (
            "Start adding your expenses to get smart insights."
        )

    elif top_category != "None":

        smart_insight = (
            f"Your highest spending category is "
            f"{top_category} with ₹{top_category_amount:.2f}."
        )

    else:

        smart_insight = "Keep tracking your expenses."

    # ALERT
    if change_percentage > 20:

        expense_alert = (
            "⚠️ Your expenses increased significantly "
            "compared to last month."
        )

    elif change_percentage < -20:

        expense_alert = (
            "✅ Great! Your expenses decreased "
            "compared to last month."
        )

    else:

        expense_alert = (
            "ℹ️ Your spending is relatively stable."
        )

    # BUDGET
    budget_row = conn.execute(
        """
        SELECT amount
        FROM budgets
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    if budget_row:

        monthly_budget = float(budget_row["amount"])

    else:

        monthly_budget = 0

    if monthly_budget > 0:

        budget_used = current_month_total

        budget_remaining = (
            monthly_budget - budget_used
        )

        budget_percentage = (
            budget_used / monthly_budget
        ) * 100

        if budget_percentage >= 100:

            budget_status = "danger"

        elif budget_percentage >= 75:

            budget_status = "warning"

        else:

            budget_status = "safe"

    else:

        budget_used = current_month_total
        budget_remaining = 0
        budget_percentage = 0
        budget_status = "safe"

    conn.close()

    return {
        "expenses": expenses,
        "total_expense": total_expense,
        "average_expense": average_expense,
        "highest_expense": highest_expense,
        "highest_expense_name": highest_expense_name,
        "top_category": top_category,
        "top_category_amount": top_category_amount,
        "current_month": current_month,
        "current_month_total": current_month_total,
        "previous_month": previous_month_key,
        "previous_month_total": previous_month_total,
        "today_total": today_total,
        "change_amount": change_amount,
        "change_percentage": change_percentage,
        "smart_insight": smart_insight,
        "expense_alert": expense_alert,
        "monthly_budget": monthly_budget,
        "budget_used": budget_used,
        "budget_remaining": budget_remaining,
        "budget_percentage": budget_percentage,
        "budget_status": budget_status,
        "category_totals": category_totals,
        "category_data": category_totals,
        "monthly_labels": monthly_labels,
        "monthly_totals": monthly_totals,
        "monthly_data": monthly_totals
    }


# ============================================================
# HOME
# ============================================================

@app.route("/")
@login_required
def home():

    data = get_dashboard_data(session["user_id"])

    categories = [
        "Food",
        "Travel",
        "Shopping",
        "Bills",
        "Entertainment",
        "Health",
        "Education",
        "Other"
    ]

    data["categories"] = categories

    return render_template(
        "index.html",
        **data
    )


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if not username or not password:

            flash(
                "Please enter username and password.",
                "danger"
            )

            return redirect(url_for("login"))

        conn = get_db()

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        conn.close()

        if user and check_password_hash(
            user["password"],
            password
        ):

            session.clear()

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect(url_for("home"))

        flash(
            "Invalid username or password.",
            "danger"
        )

        return redirect(url_for("login"))

    return render_template("login.html")


# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get(
            "username",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if not username or not password:

            flash(
                "Username and password are required.",
                "danger"
            )

            return redirect(url_for("register"))

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger"
            )

            return redirect(url_for("register"))

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "danger"
            )

            return redirect(url_for("register"))

        conn = get_db()

        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if existing:

            conn.close()

            flash(
                "Username already exists.",
                "danger"
            )

            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        conn.execute(
            """
            INSERT INTO users
            (username, password)
            VALUES (?, ?)
            """,
            (username, password_hash)
        )

        conn.commit()
        conn.close()

        flash(
            "Registration successful. Please login.",
            "success"
        )

        return redirect(url_for("login"))

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

@app.route("/add_expense", methods=["POST"])
@login_required
def add_expense():

    name = request.form.get(
        "name",
        request.form.get("description", "")
    ).strip()

    amount_text = request.form.get(
        "amount",
        "0"
    )

    category = request.form.get(
        "category",
        "Other"
    )

    expense_date = request.form.get(
        "expense_date",
        date.today().isoformat()
    )

    try:

        amount = float(amount_text)

    except ValueError:

        flash(
            "Invalid amount.",
            "danger"
        )

        return redirect(url_for("home"))

    if not name or amount <= 0:

        flash(
            "Please enter valid expense details.",
            "danger"
        )

        return redirect(url_for("home"))

    conn = get_db()

    conn.execute(
        """
        INSERT INTO expenses
        (
            user_id,
            name,
            amount,
            category,
            expense_date,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session["user_id"],
            name,
            amount,
            category,
            expense_date,
            datetime.now().isoformat()
        )
    )

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

@app.route("/delete_expense/<int:expense_id>", methods=["POST", "GET"])
@login_required
def delete_expense(expense_id):

    conn = get_db()

    conn.execute(
        """
        DELETE FROM expenses
        WHERE id = ?
        AND user_id = ?
        """,
        (
            expense_id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    flash(
        "Expense deleted successfully.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# EDIT EXPENSE
# ============================================================

@app.route("/edit_expense/<int:expense_id>", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):

    conn = get_db()

    expense = conn.execute(
        """
        SELECT *
        FROM expenses
        WHERE id = ?
        AND user_id = ?
        """,
        (
            expense_id,
            session["user_id"]
        )
    ).fetchone()

    if not expense:

        conn.close()

        flash(
            "Expense not found.",
            "danger"
        )

        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        amount_text = request.form.get(
            "amount",
            "0"
        )

        category = request.form.get(
            "category",
            "Other"
        )

        expense_date = request.form.get(
            "expense_date",
            date.today().isoformat()
        )

        try:

            amount = float(amount_text)

        except ValueError:

            conn.close()

            flash(
                "Invalid amount.",
                "danger"
            )

            return redirect(
                url_for(
                    "edit_expense",
                    expense_id=expense_id
                )
            )

        conn.execute(
            """
            UPDATE expenses
            SET
                name = ?,
                amount = ?,
                category = ?,
                expense_date = ?
            WHERE id = ?
            AND user_id = ?
            """,
            (
                name,
                amount,
                category,
                expense_date,
                expense_id,
                session["user_id"]
            )
        )

        conn.commit()
        conn.close()

        flash(
            "Expense updated successfully.",
            "success"
        )

        return redirect(url_for("home"))

    conn.close()

    categories = [
        "Food",
        "Travel",
        "Shopping",
        "Bills",
        "Entertainment",
        "Health",
        "Education",
        "Other"
    ]

    return render_template(
        "edit_expense.html",
        expense=expense,
        categories=categories
    )


# ============================================================
# SET BUDGET
# ============================================================

@app.route("/set_budget", methods=["POST"])
@login_required
def set_budget():

    amount_text = request.form.get(
        "budget",
        request.form.get("amount", "0")
    )

    try:

        amount = float(amount_text)

    except ValueError:

        flash(
            "Invalid budget amount.",
            "danger"
        )

        return redirect(url_for("home"))

    conn = get_db()

    existing = conn.execute(
        """
        SELECT id
        FROM budgets
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if existing:

        conn.execute(
            """
            UPDATE budgets
            SET amount = ?
            WHERE user_id = ?
            """,
            (
                amount,
                session["user_id"]
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO budgets
            (user_id, amount)
            VALUES (?, ?)
            """,
            (
                session["user_id"],
                amount
            )
        )

    conn.commit()
    conn.close()

    flash(
        "Monthly budget updated.",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/health")
def health():

    return {
        "status": "ok",
        "database": "connected"
    }


# ============================================================
# RUN LOCAL
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
    print("==========================================")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )