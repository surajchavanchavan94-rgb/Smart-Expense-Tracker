
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    Response
)
from functools import wraps
import sqlite3
import csv
import io
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
import os


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = "smart-expense-tracker-final-secret-key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "expenses.db")
BUDGET_FILE = os.path.join(BASE_DIR, "budget.txt")


# ============================================================
# CONSTANTS
# ============================================================

CATEGORIES = [
    "Food",
    "Travel",
    "Shopping",
    "Bills",
    "Education",
    "Entertainment",
    "Health",
    "Other"
]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    conn = get_db()

    # ---------------- USERS ----------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT
        )
    """)

    # Add password_hash if an older database needs it
    user_columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    ]

    if "password_hash" not in user_columns:
        try:
            conn.execute(
                "ALTER TABLE users ADD COLUMN password_hash TEXT"
            )
        except sqlite3.OperationalError:
            pass

    # ---------------- EXPENSES ----------------

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

    expense_columns = [
        row["name"]
        for row in conn.execute("PRAGMA table_info(expenses)").fetchall()
    ]

    # Add missing columns to old databases
    if "created_at" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN created_at TEXT"
        )

        conn.execute("""
            UPDATE expenses
            SET created_at = ?
            WHERE created_at IS NULL
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))

    if "user_id" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN user_id INTEGER"
        )

    if "description" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN description TEXT"
        )

    if "expense_date" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN expense_date TEXT"
        )

        conn.execute("""
            UPDATE expenses
            SET expense_date = ?
            WHERE expense_date IS NULL
        """, (
            date.today().isoformat(),
        ))

    if "name" not in expense_columns:
        conn.execute(
            "ALTER TABLE expenses ADD COLUMN name TEXT"
        )

    # ---------------- BUDGETS ----------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            amount REAL DEFAULT 0
        )
    """)

    # ---------------- DEFAULT ADMIN ----------------

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

        # Make sure old admin has a usable password
        if "password_hash" in user_columns:

            if not admin["password_hash"]:
                password_hash = generate_password_hash("admin123")

                try:
                    conn.execute("""
                        UPDATE users
                        SET password_hash = ?
                        WHERE username = 'admin'
                    """, (password_hash,))
                except Exception:
                    pass

        if "password" in user_columns:

            try:
                if not admin["password"]:
                    password_hash = generate_password_hash("admin123")

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
# LOGIN REQUIRED
# ============================================================

def login_required(func):

    @wraps(func)
    def wrapper(*args, **kwargs):

        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))

        return func(*args, **kwargs)

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

    # Backward compatibility with budget.txt
    try:
        if os.path.exists(BUDGET_FILE):
            with open(BUDGET_FILE, "r") as file:
                value = float(file.read().strip() or 0)
                return value
    except Exception:
        pass

    return 0.0


def save_budget(user_id, amount):

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

    try:
        with open(BUDGET_FILE, "w") as file:
            file.write(str(amount))
    except Exception:
        pass


# ============================================================
# DASHBOARD CALCULATIONS
# ============================================================

def calculate_dashboard(user_id, search_query=""):

    conn = get_db()

    # ---------------- EXPENSES ----------------

    if search_query:

        like_query = f"%{search_query}%"

        expenses = conn.execute("""
            SELECT *
            FROM expenses
            WHERE user_id = ?
            AND (
                name LIKE ?
                OR category LIKE ?
                OR description LIKE ?
            )
            ORDER BY expense_date DESC, id DESC
        """, (
            user_id,
            like_query,
            like_query,
            like_query
        )).fetchall()

    else:

        expenses = conn.execute("""
            SELECT *
            FROM expenses
            WHERE user_id = ?
            ORDER BY expense_date DESC, id DESC
        """, (user_id,)).fetchall()

    # ---------------- TOTAL ----------------

    total_row = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    total_expense = float(total_row["total"] or 0)

    # ---------------- AVERAGE ----------------

    average_row = conn.execute("""
        SELECT COALESCE(AVG(amount), 0) AS average
        FROM expenses
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    average_expense = float(average_row["average"] or 0)

    # ---------------- HIGHEST ----------------

    highest_row = conn.execute("""
        SELECT name, amount
        FROM expenses
        WHERE user_id = ?
        ORDER BY amount DESC
        LIMIT 1
    """, (user_id,)).fetchone()

    if highest_row:

        highest_expense = float(highest_row["amount"] or 0)
        highest_expense_name = highest_row["name"] or "Unknown"

    else:

        highest_expense = 0.0
        highest_expense_name = "No expense"

    # ---------------- TOP CATEGORY ----------------

    top_category_row = conn.execute("""
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY total DESC
        LIMIT 1
    """, (user_id,)).fetchone()

    if top_category_row:

        top_category = top_category_row["category"]
        top_category_amount = float(
            top_category_row["total"] or 0
        )

    else:

        top_category = "None"
        top_category_amount = 0.0

    # ---------------- CURRENT MONTH ----------------

    now = datetime.now()

    current_month = now.strftime("%B %Y")
    current_month_key = now.strftime("%Y-%m")

    current_month_row = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
        AND substr(expense_date, 1, 7) = ?
    """, (
        user_id,
        current_month_key
    )).fetchone()

    current_month_total = float(
        current_month_row["total"] or 0
    )

    # ---------------- PREVIOUS MONTH ----------------

    if now.month == 1:

        previous_year = now.year - 1
        previous_month_number = 12

    else:

        previous_year = now.year
        previous_month_number = now.month - 1

    previous_month_key = (
        f"{previous_year:04d}-{previous_month_number:02d}"
    )

    previous_month_name = datetime(
        previous_year,
        previous_month_number,
        1
    ).strftime("%B %Y")

    previous_month_row = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
        AND substr(expense_date, 1, 7) = ?
    """, (
        user_id,
        previous_month_key
    )).fetchone()

    previous_month_total = float(
        previous_month_row["total"] or 0
    )

    # ---------------- MONTHLY CHANGE ----------------

    change_amount = (
        current_month_total - previous_month_total
    )

    if previous_month_total > 0:

        change_percentage = (
            change_amount / previous_month_total
        ) * 100

    else:

        change_percentage = 100.0 if current_month_total > 0 else 0.0

    # ---------------- TODAY ----------------

    today_key = date.today().isoformat()

    today_row = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE user_id = ?
        AND expense_date = ?
    """, (
        user_id,
        today_key
    )).fetchone()

    today_total = float(today_row["total"] or 0)

    # ---------------- CATEGORY DATA ----------------

    category_rows = conn.execute("""
        SELECT category, SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
        GROUP BY category
        ORDER BY total DESC
    """, (user_id,)).fetchall()

    category_totals_map = {
        row["category"]: float(row["total"] or 0)
        for row in category_rows
    }

    # IMPORTANT:
    # Always send all categories to index.html
    category_labels = CATEGORIES.copy()

    category_totals = [
        category_totals_map.get(category, 0)
        for category in category_labels
    ]

    # ---------------- MONTHLY DATA ----------------

    monthly_rows = conn.execute("""
        SELECT
            substr(expense_date, 1, 7) AS month_key,
            SUM(amount) AS total
        FROM expenses
        WHERE user_id = ?
        GROUP BY substr(expense_date, 1, 7)
        ORDER BY month_key ASC
        LIMIT 12
    """, (user_id,)).fetchall()

    monthly_labels = []

    monthly_totals = []

    for row in monthly_rows:

        try:
            month_date = datetime.strptime(
                row["month_key"],
                "%Y-%m"
            )

            monthly_labels.append(
                month_date.strftime("%b %Y")
            )

        except Exception:

            monthly_labels.append(
                row["month_key"]
            )

        monthly_totals.append(
            float(row["total"] or 0)
        )

    conn.close()

    # ---------------- BUDGET ----------------

    monthly_budget = get_budget(user_id)

    budget_used = current_month_total

    if monthly_budget > 0:

        budget_percentage = (
            budget_used / monthly_budget
        ) * 100

    else:

        budget_percentage = 0

    budget_remaining = monthly_budget - budget_used

    if budget_remaining < 0:
        budget_remaining = 0

    if monthly_budget <= 0:

        budget_status = "none"

    elif budget_percentage >= 100:

        budget_status = "danger"

    elif budget_percentage >= 75:

        budget_status = "warning"

    else:

        budget_status = "safe"

    # ---------------- SMART INSIGHT ----------------

    if total_expense <= 0:

        smart_insight = (
            "No expenses recorded yet. "
            "Start adding your expenses to get smart insights."
        )

    elif top_category != "None":

        smart_insight = (
            f"Your highest spending category is "
            f"{top_category} with "
            f"₹{top_category_amount:.2f} spent."
        )

    else:

        smart_insight = "Keep tracking your expenses regularly."

    # ---------------- EXPENSE ALERT ----------------

    if previous_month_total <= 0 and current_month_total > 0:

        expense_alert = (
            "You have started spending this month. "
            "Keep an eye on your budget."
        )

    elif change_percentage > 20:

        expense_alert = (
            "⚠️ Your expenses are significantly higher "
            "than the previous month."
        )

    elif change_percentage < -20:

        expense_alert = (
            "✅ Great! Your expenses are lower "
            "than the previous month."
        )

    else:

        expense_alert = (
            "Your spending is relatively stable "
            "compared with the previous month."
        )

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
        "previous_month": previous_month_name,
        "previous_month_total": previous_month_total,
        "change_amount": change_amount,
        "change_percentage": change_percentage,
        "today_total": today_total,
        "categories": category_labels,
        "category_totals": category_totals,
        "monthly_labels": monthly_labels,
        "monthly_totals": monthly_totals,
        "monthly_budget": monthly_budget,
        "budget_used": budget_used,
        "budget_remaining": budget_remaining,
        "budget_percentage": budget_percentage,
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

    search_query = request.args.get(
        "q",
        ""
    ).strip()

    data = calculate_dashboard(
        session["user_id"],
        search_query
    )

    return render_template(
        "index.html",
        username=session.get("username", "User"),
        today_date=date.today().isoformat(),
        search_query=search_query,
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

        conn = get_db()

        user = conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        conn.close()

        if not user:

            flash(
                "Invalid username or password.",
                "error"
            )

            return redirect(url_for("login"))

        valid_password = False

        # password_hash column
        try:

            password_hash = user["password_hash"]

            if password_hash:
                valid_password = check_password_hash(
                    password_hash,
                    password
                )

        except Exception:
            pass

        # old password column
        if not valid_password:

            try:

                stored_password = user["password"]

                if stored_password:

                    try:

                        valid_password = check_password_hash(
                            stored_password,
                            password
                        )

                    except Exception:

                        valid_password = (
                            stored_password == password
                        )

            except Exception:
                pass

        if valid_password:

            session.clear()

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            return redirect(url_for("home"))

        flash(
            "Invalid username or password.",
            "error"
        )

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
                "error"
            )

            return redirect(url_for("register"))

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "error"
            )

            return redirect(url_for("register"))

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
            conn.close()

            flash(
                "Registration successful! Please login.",
                "success"
            )

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:

            conn.close()

            flash(
                "Username already exists.",
                "error"
            )

            return redirect(url_for("register"))

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
        ""
    ).strip()

    amount = request.form.get(
        "amount",
        ""
    ).strip()

    category = request.form.get(
        "category",
        ""
    ).strip()

    description = request.form.get(
        "description",
        ""
    ).strip()

    expense_date = request.form.get(
        "expense_date",
        ""
    ).strip()

    if not name or not amount or not category:

        flash(
            "Please fill all required fields.",
            "error"
        )

        return redirect(url_for("home"))

    if category not in CATEGORIES:

        flash(
            "Please select a valid category.",
            "error"
        )

        return redirect(url_for("home"))

    try:

        amount = float(amount)

        if amount <= 0:
            raise ValueError

    except ValueError:

        flash(
            "Please enter a valid amount.",
            "error"
        )

        return redirect(url_for("home"))

    if not expense_date:
        expense_date = date.today().isoformat()

    # THIS FIXES YOUR CURRENT ERROR
    created_at = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

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
        created_at,
        session["user_id"],
        name
    ))

    conn.commit()
    conn.close()

    flash(
        "Expense added successfully! ✅",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# SET BUDGET
# ============================================================

@app.route("/set_budget", methods=["POST"])
@login_required
def set_budget():

    budget = request.form.get(
        "budget",
        "0"
    ).strip()

    try:

        budget = float(budget)

        if budget < 0:
            raise ValueError

    except ValueError:

        flash(
            "Please enter a valid budget.",
            "error"
        )

        return redirect(url_for("home"))

    save_budget(
        session["user_id"],
        budget
    )

    flash(
        "Monthly budget updated successfully! ✅",
        "success"
    )

    return redirect(url_for("home"))


# ============================================================
# SEARCH
# ============================================================

@app.route("/search")
@login_required
def search():

    query = request.args.get(
        "q",
        ""
    ).strip()

    return redirect(
        url_for(
            "home",
            q=query
        )
    )


# ============================================================
# CLEAR SEARCH
# ============================================================

@app.route("/clear_search")
@login_required
def clear_search():

    return redirect(url_for("home"))


# ============================================================
# DELETE EXPENSE
# ============================================================

@app.route("/delete_expense/<int:expense_id>")
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
# EDIT EXPENSE
# ============================================================

@app.route(
    "/edit_expense/<int:expense_id>",
    methods=["GET", "POST"]
)
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

        name = request.form.get(
            "name",
            ""
        ).strip()

        amount = request.form.get(
            "amount",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        expense_date = request.form.get(
            "expense_date",
            ""
        ).strip()

        try:

            amount = float(amount)

            if amount <= 0:
                raise ValueError

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

            conn.close()

            flash(
                "Invalid category.",
                "error"
            )

            return redirect(
                url_for(
                    "edit_expense",
                    expense_id=expense_id
                )
            )

        conn.execute("""
            UPDATE expenses
            SET
                name = ?,
                amount = ?,
                category = ?,
                description = ?,
                expense_date = ?
            WHERE id = ?
            AND user_id = ?
        """, (
            name,
            amount,
            category,
            description,
            expense_date,
            expense_id,
            session["user_id"]
        ))

        conn.commit()
        conn.close()

        flash(
            "Expense updated successfully! ✅",
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
# DOWNLOAD CSV
# ============================================================

@app.route("/download_csv")
@login_required
def download_csv():

    conn = get_db()

    expenses = conn.execute("""
        SELECT
            expense_date,
            name,
            amount,
            category,
            description
        FROM expenses
        WHERE user_id = ?
        ORDER BY expense_date DESC, id DESC
    """, (
        session["user_id"],
    )).fetchall()

    conn.close()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Date",
        "Name",
        "Amount",
        "Category",
        "Description"
    ])

    for expense in expenses:

        writer.writerow([
            expense["expense_date"],
            expense["name"],
            expense["amount"],
            expense["category"],
            expense["description"] or ""
        ])

    csv_data = output.getvalue()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=smart_expenses.csv"
        }
    )


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    init_db()

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
    print()

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )

