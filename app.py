from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
import os
import sqlite3
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "secret123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = os.environ.get("VERCEL") == "1"
DATA_DIR = os.environ.get("DATA_DIR") or ("/tmp" if IS_VERCEL else BASE_DIR)
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(DATA_DIR, "database.db")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
STATUS_OPTIONS = ["Pending", "In Progress", "Resolved"]
CATEGORY_OPTIONS = ["Road", "Garbage", "Water", "Electricity"]
DEFAULT_ADMIN = {
    "name": "System Admin",
    "email": "admin@civictrack.local",
    "password": "admin123",
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["DATABASE_PATH"] = DATABASE_PATH
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)


def get_db():
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.row_factory = sqlite3.Row
    return db


def ensure_database():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            image TEXT,
            created_at TEXT
        )
        """
    )

    columns = {row["name"] for row in db.execute("PRAGMA table_info(complaints)").fetchall()}
    if "user_id" not in columns:
        db.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER")
    if "location" not in columns:
        db.execute("ALTER TABLE complaints ADD COLUMN location TEXT")
    if "created_at" not in columns:
        db.execute("ALTER TABLE complaints ADD COLUMN created_at TEXT")

    admin = db.execute("SELECT id FROM admins WHERE email = ?", (DEFAULT_ADMIN["email"],)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO admins (name, email, password) VALUES (?, ?, ?)",
            (DEFAULT_ADMIN["name"], DEFAULT_ADMIN["email"], DEFAULT_ADMIN["password"]),
        )

    db.commit()
    db.close()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(image):
    if not image or not image.filename:
        return None, None

    if not allowed_file(image.filename):
        return None, "Please upload a valid image file (PNG, JPG, JPEG, GIF, or WEBP)."

    filename = secure_filename(image.filename)
    extension = filename.rsplit(".", 1)[1].lower()
    image_name = f"{uuid.uuid4().hex}.{extension}"
    image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_name))
    return image_name, None


def get_site_summary():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM complaints WHERE status = 'Pending'").fetchone()[0]
    in_progress = db.execute("SELECT COUNT(*) FROM complaints WHERE status = 'In Progress'").fetchone()[0]
    resolved = db.execute("SELECT COUNT(*) FROM complaints WHERE status = 'Resolved'").fetchone()[0]
    db.close()
    return {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "resolved": resolved,
    }


def get_user_summary(user_id):
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM complaints WHERE user_id = ?", (user_id,)).fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM complaints WHERE user_id = ? AND status = 'Pending'",
        (user_id,),
    ).fetchone()[0]
    in_progress = db.execute(
        "SELECT COUNT(*) FROM complaints WHERE user_id = ? AND status = 'In Progress'",
        (user_id,),
    ).fetchone()[0]
    resolved = db.execute(
        "SELECT COUNT(*) FROM complaints WHERE user_id = ? AND status = 'Resolved'",
        (user_id,),
    ).fetchone()[0]
    db.close()
    return {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "resolved": resolved,
    }


def get_admin_chart_data():
    db = get_db()
    category_rows = db.execute(
        """
        SELECT category, COUNT(*) AS total
        FROM complaints
        GROUP BY category
        ORDER BY total DESC, category ASC
        """
    ).fetchall()
    status_rows = db.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM complaints
        GROUP BY status
        ORDER BY total DESC
        """
    ).fetchall()
    db.close()
    return {
        "category_labels": [row["category"] for row in category_rows],
        "category_values": [row["total"] for row in category_rows],
        "status_labels": [row["status"] for row in status_rows],
        "status_values": [row["total"] for row in status_rows],
    }


def require_user():
    return session.get("role") == "user" and session.get("user_id")


def require_admin():
    return session.get("role") == "admin" and session.get("admin_id")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/")
def index():
    return render_template(
        "index.html",
        summary=get_site_summary(),
        categories=CATEGORY_OPTIONS,
        default_admin=DEFAULT_ADMIN,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            error = "All fields are required."
        else:
            db = get_db()
            existing_user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing_user:
                error = "An account with that email already exists."
            else:
                db.execute(
                    "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                    (name, email, password),
                )
                db.commit()
                db.close()
                return redirect(url_for("login"))
            db.close()

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if session.get("role") == "user":
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email, password),
        ).fetchone()
        db.close()

        if user:
            session.clear()
            session["role"] = "user"
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("dashboard"))

        error = "Invalid user credentials. Please try again."

    return render_template("login.html", error=error)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None

    if session.get("role") == "admin":
        return redirect(url_for("admin"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        db = get_db()
        admin_user = db.execute(
            "SELECT * FROM admins WHERE email = ? AND password = ?",
            (email, password),
        ).fetchone()
        db.close()

        if admin_user:
            session.clear()
            session["role"] = "admin"
            session["admin_id"] = admin_user["id"]
            session["admin_name"] = admin_user["name"]
            return redirect(url_for("admin"))

        error = "Invalid admin credentials. Please try again."

    return render_template("admin_login.html", error=error, default_admin=DEFAULT_ADMIN)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    if not require_user():
        return redirect(url_for("login"))

    db = get_db()
    complaints = db.execute(
        """
        SELECT *
        FROM complaints
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    db.close()
    return render_template(
        "dashboard.html",
        complaints=complaints,
        summary=get_user_summary(session["user_id"]),
    )


@app.route("/add", methods=["GET", "POST"])
def add():
    if not require_user():
        return redirect(url_for("login"))

    error = None

    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form["description"].strip()
        category = request.form["category"]
        location = request.form["location"].strip()
        image_name, upload_error = save_uploaded_image(request.files.get("image"))

        if upload_error:
            error = upload_error
        elif category not in CATEGORY_OPTIONS:
            error = "Please select a valid category."
        elif not title or not description or not location:
            error = "Title, description, and location are required."
        else:
            db = get_db()
            db.execute(
                """
                INSERT INTO complaints (user_id, title, description, category, location, status, image, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"],
                    title,
                    description,
                    category,
                    location,
                    "Pending",
                    image_name,
                    datetime.now().strftime("%d %b %Y, %I:%M %p"),
                ),
            )
            db.commit()
            db.close()
            return redirect(url_for("dashboard"))

    return render_template("add_complaint.html", error=error, categories=CATEGORY_OPTIONS)


@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))

    category_filter = request.args.get("category", "All")
    query = """
        SELECT complaints.*, users.name AS resident_name, users.email AS resident_email
        FROM complaints
        LEFT JOIN users ON users.id = complaints.user_id
    """
    params = []

    if category_filter != "All":
        query += " WHERE complaints.category = ?"
        params.append(category_filter)

    query += " ORDER BY complaints.id DESC"

    db = get_db()
    complaints = db.execute(query, params).fetchall()
    db.close()

    return render_template(
        "admin.html",
        complaints=complaints,
        summary=get_site_summary(),
        categories=["All"] + CATEGORY_OPTIONS,
        active_category=category_filter,
        chart_data=get_admin_chart_data(),
        status_options=STATUS_OPTIONS,
    )


@app.route("/admin/update/<int:complaint_id>", methods=["POST"])
def admin_update_status(complaint_id):
    if not require_admin():
        return redirect(url_for("admin_login"))

    status = request.form["status"]
    if status not in STATUS_OPTIONS:
        return redirect(url_for("admin"))

    db = get_db()
    db.execute("UPDATE complaints SET status = ? WHERE id = ?", (status, complaint_id))
    db.commit()
    db.close()
    return redirect(url_for("admin", category=request.args.get("category", "All")))


if __name__ == "__main__":
    ensure_database()
    app.run(debug=True)
else:
    ensure_database()
