from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, session, url_for, send_from_directory
import os
import sqlite3
import uuid
from werkzeug.utils import secure_filename

try:
    from supabase import Client, create_client
except ImportError:
    Client = None
    create_client = None

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret123")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IS_VERCEL = os.environ.get("VERCEL") == "1"
DATA_DIR = os.environ.get("DATA_DIR") or ("/tmp" if IS_VERCEL else BASE_DIR)
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads")
DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(DATA_DIR, "database.db")
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip() or None
SUPABASE_KEY = (
    (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or "").strip()
    or None
)
SUPABASE_BUCKET = (os.environ.get("SUPABASE_BUCKET") or "complaint-images").strip()

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

_supabase_client = None


def supabase_enabled():
    return bool(SUPABASE_URL and SUPABASE_KEY and create_client)


def get_supabase():
    global _supabase_client
    if not supabase_enabled():
        return None
    if _supabase_client is None:
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def supabase_ready():
    if not supabase_enabled():
        return False

    try:
        get_supabase().table("admins").select("id").limit(1).execute()
        return True
    except Exception:
        return False


def get_db():
    db = sqlite3.connect(app.config["DATABASE_PATH"])
    db.row_factory = sqlite3.Row
    return db


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def format_created_at(value):
    if not value:
        return "Recently"

    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %I:%M %p")
    except ValueError:
        return str(value)


def build_image_url(image_value):
    if not image_value:
        return None

    if str(image_value).startswith("http://") or str(image_value).startswith("https://"):
        return image_value

    if supabase_ready():
        try:
            public_url = get_supabase().storage.from_(SUPABASE_BUCKET).get_public_url(image_value)
            if isinstance(public_url, dict):
                return public_url.get("publicUrl") or public_url.get("public_url")
            return public_url
        except Exception:
            return None

    return url_for("uploaded_file", filename=image_value)


def normalize_complaint(row, users_map=None):
    complaint = dict(row)
    complaint["created_at"] = format_created_at(complaint.get("created_at"))
    complaint["image_url"] = build_image_url(complaint.get("image"))

    user_id = complaint.get("user_id")
    if users_map and user_id in users_map:
        complaint["resident_name"] = users_map[user_id].get("name")
        complaint["resident_email"] = users_map[user_id].get("email")

    return complaint


def fetch_all_users_map():
    if supabase_ready():
        response = get_supabase().table("users").select("id, name, email").execute()
        rows = response.data or []
    else:
        db = get_db()
        rows = [dict(row) for row in db.execute("SELECT id, name, email FROM users").fetchall()]
        db.close()

    return {row["id"]: row for row in rows}


def get_user_by_email(email):
    if supabase_ready():
        response = get_supabase().table("users").select("*").eq("email", email).limit(1).execute()
        rows = response.data or []
        return rows[0] if rows else None

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    db.close()
    return dict(row) if row else None


def get_user_by_credentials(email, password):
    if supabase_ready():
        response = (
            get_supabase()
            .table("users")
            .select("*")
            .eq("email", email)
            .eq("password", password)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    db = get_db()
    row = db.execute(
        "SELECT * FROM users WHERE email = ? AND password = ?",
        (email, password),
    ).fetchone()
    db.close()
    return dict(row) if row else None


def get_admin_by_credentials(email, password):
    if supabase_ready():
        response = (
            get_supabase()
            .table("admins")
            .select("*")
            .eq("email", email)
            .eq("password", password)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None

    db = get_db()
    row = db.execute(
        "SELECT * FROM admins WHERE email = ? AND password = ?",
        (email, password),
    ).fetchone()
    db.close()
    return dict(row) if row else None


def create_user_record(name, email, password):
    if supabase_ready():
        get_supabase().table("users").insert(
            {"name": name, "email": email, "password": password}
        ).execute()
        return

    db = get_db()
    db.execute(
        "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
        (name, email, password),
    )
    db.commit()
    db.close()


def fetch_complaints_for_user(user_id):
    if supabase_ready():
        response = (
            get_supabase()
            .table("complaints")
            .select("*")
            .eq("user_id", user_id)
            .order("id", desc=True)
            .execute()
        )
        rows = response.data or []
        return [normalize_complaint(row) for row in rows]

    db = get_db()
    rows = [
        normalize_complaint(dict(row))
        for row in db.execute(
            """
            SELECT *
            FROM complaints
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()
    ]
    db.close()
    return rows


def fetch_all_complaints(category_filter="All"):
    users_map = fetch_all_users_map()

    if supabase_ready():
        query = get_supabase().table("complaints").select("*").order("id", desc=True)
        if category_filter != "All":
            query = query.eq("category", category_filter)
        rows = query.execute().data or []
        return [normalize_complaint(row, users_map) for row in rows]

    db = get_db()
    if category_filter != "All":
        fetched = db.execute(
            "SELECT * FROM complaints WHERE category = ? ORDER BY id DESC",
            (category_filter,),
        ).fetchall()
    else:
        fetched = db.execute("SELECT * FROM complaints ORDER BY id DESC").fetchall()
    db.close()
    return [normalize_complaint(dict(row), users_map) for row in fetched]


def calculate_summary(complaints):
    summary = {"total": 0, "pending": 0, "in_progress": 0, "resolved": 0}
    summary["total"] = len(complaints)

    for complaint in complaints:
        if complaint["status"] == "Pending":
            summary["pending"] += 1
        elif complaint["status"] == "In Progress":
            summary["in_progress"] += 1
        elif complaint["status"] == "Resolved":
            summary["resolved"] += 1

    return summary


def get_site_summary():
    return calculate_summary(fetch_all_complaints())


def get_user_summary(user_id):
    return calculate_summary(fetch_complaints_for_user(user_id))


def get_admin_chart_data():
    complaints = fetch_all_complaints()
    category_totals = {category: 0 for category in CATEGORY_OPTIONS}
    status_totals = {status: 0 for status in STATUS_OPTIONS}

    for complaint in complaints:
        category_totals[complaint["category"]] = category_totals.get(complaint["category"], 0) + 1
        status_totals[complaint["status"]] = status_totals.get(complaint["status"], 0) + 1

    return {
        "category_labels": list(category_totals.keys()),
        "category_values": list(category_totals.values()),
        "status_labels": list(status_totals.keys()),
        "status_values": list(status_totals.values()),
    }


def save_uploaded_image(image):
    if not image or not image.filename:
        return None, None

    if not allowed_file(image.filename):
        return None, "Please upload a valid image file (PNG, JPG, JPEG, GIF, or WEBP)."

    filename = secure_filename(image.filename)
    extension = filename.rsplit(".", 1)[1].lower()
    image_name = f"{uuid.uuid4().hex}.{extension}"

    if supabase_ready():
        storage_path = f"complaints/{image_name}"
        image.stream.seek(0)
        get_supabase().storage.from_(SUPABASE_BUCKET).upload(
            path=storage_path,
            file=image.stream.read(),
            file_options={
                "content-type": image.mimetype or "application/octet-stream",
                "upsert": "false",
            },
        )
        return storage_path, None

    image_path = os.path.join(app.config["UPLOAD_FOLDER"], image_name)
    image.save(image_path)
    return image_name, None


def create_complaint_record(user_id, title, description, category, location, image_name):
    created_at = datetime.now(timezone.utc).isoformat()

    if supabase_ready():
        get_supabase().table("complaints").insert(
            {
                "user_id": user_id,
                "title": title,
                "description": description,
                "category": category,
                "location": location,
                "status": "Pending",
                "image": image_name,
                "created_at": created_at,
            }
        ).execute()
        return

    db = get_db()
    db.execute(
        """
        INSERT INTO complaints (user_id, title, description, category, location, status, image, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, title, description, category, location, "Pending", image_name, created_at),
    )
    db.commit()
    db.close()


def update_complaint_status(complaint_id, status):
    if supabase_ready():
        get_supabase().table("complaints").update({"status": status}).eq("id", complaint_id).execute()
        return

    db = get_db()
    db.execute("UPDATE complaints SET status = ? WHERE id = ?", (status, complaint_id))
    db.commit()
    db.close()


def ensure_local_database():
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
    admin = db.execute("SELECT id FROM admins WHERE email = ?", (DEFAULT_ADMIN["email"],)).fetchone()
    if not admin:
        db.execute(
            "INSERT INTO admins (name, email, password) VALUES (?, ?, ?)",
            (DEFAULT_ADMIN["name"], DEFAULT_ADMIN["email"], DEFAULT_ADMIN["password"]),
        )
    db.commit()
    db.close()


def ensure_supabase_admin():
    if not supabase_enabled():
        return

    try:
        response = (
            get_supabase()
            .table("admins")
            .select("id")
            .eq("email", DEFAULT_ADMIN["email"])
            .limit(1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            get_supabase().table("admins").insert(DEFAULT_ADMIN).execute()
    except Exception:
        pass


def require_user():
    return session.get("role") == "user" and session.get("user_id")


def require_admin():
    return session.get("role") == "admin" and session.get("admin_id")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.route("/")
def index():
    return render_template("index.html", summary=get_site_summary())


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or not password:
            error = "All fields are required."
        elif get_user_by_email(email):
            error = "An account with that email already exists."
        else:
            create_user_record(name, email, password)
            return redirect(url_for("login"))

    return render_template("register.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if session.get("role") == "user":
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = get_user_by_credentials(email, password)

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
    if session.get("role") == "user":
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        admin_user = get_admin_by_credentials(email, password)

        if admin_user:
            session.clear()
            session["role"] = "admin"
            session["admin_id"] = admin_user["id"]
            session["admin_name"] = admin_user["name"]
            return redirect(url_for("admin"))

        error = "Invalid admin credentials. Please try again."

    return render_template("admin_login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    if not require_user():
        return redirect(url_for("login"))

    complaints = fetch_complaints_for_user(session["user_id"])
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
            create_complaint_record(
                session["user_id"],
                title,
                description,
                category,
                location,
                image_name,
            )
            return redirect(url_for("dashboard"))

    return render_template("add_complaint.html", error=error, categories=CATEGORY_OPTIONS)


@app.route("/admin")
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))

    category_filter = request.args.get("category", "All")
    complaints = fetch_all_complaints(category_filter)
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

    update_complaint_status(complaint_id, status)
    return redirect(url_for("admin", category=request.args.get("category", "All")))


def initialize_storage():
    if supabase_ready():
        ensure_supabase_admin()
    else:
        ensure_local_database()


initialize_storage()


if __name__ == "__main__":
    app.run(debug=True)
