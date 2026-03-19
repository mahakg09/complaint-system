import sqlite3

DEFAULT_ADMIN = ("System Admin", "admin@civictrack.local", "admin123")

conn = sqlite3.connect("database.db")
c = conn.cursor()

c.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """
)

c.execute(
    """
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL
    )
    """
)

c.execute(
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

columns = {row[1] for row in c.execute("PRAGMA table_info(complaints)").fetchall()}
if "user_id" not in columns:
    c.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER")
if "location" not in columns:
    c.execute("ALTER TABLE complaints ADD COLUMN location TEXT")
if "created_at" not in columns:
    c.execute("ALTER TABLE complaints ADD COLUMN created_at TEXT")

admin = c.execute("SELECT id FROM admins WHERE email = ?", (DEFAULT_ADMIN[1],)).fetchone()
if not admin:
    c.execute(
        "INSERT INTO admins (name, email, password) VALUES (?, ?, ?)",
        DEFAULT_ADMIN,
    )

conn.commit()
conn.close()

print("Database created successfully with default admin account.")
