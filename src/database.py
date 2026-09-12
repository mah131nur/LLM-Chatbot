import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_DIR = Path("database")
DB_PATH = DB_DIR / "chatbot.db"


def _connect():
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New Chat',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant')),
            content TEXT NOT NULL,
            domain TEXT,
            input_type TEXT NOT NULL DEFAULT 'text',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );
        """)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_session(title="New Chat"):
    stamp = now()
    with _connect() as conn:
        cur = conn.execute("INSERT INTO sessions(title,created_at,updated_at) VALUES(?,?,?)", (title, stamp, stamp))
        return cur.lastrowid


def add_message(session_id, role, content, domain=None, input_type="text"):
    stamp = now()
    with _connect() as conn:
        conn.execute("INSERT INTO messages(session_id,role,content,domain,input_type,created_at) VALUES(?,?,?,?,?,?)", (session_id, role, content, domain, input_type, stamp))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (stamp, session_id))


def set_title_if_new(session_id, title):
    title = (title or "New Chat").strip().replace("\n", " ")[:70]
    if not title:
        return
    with _connect() as conn:
        row = conn.execute("SELECT title FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row and row["title"] == "New Chat":
            conn.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?", (title, now(), session_id))


def get_session_messages(session_id):
    with _connect() as conn:
        rows = conn.execute("SELECT role,content,domain,input_type,created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        return [dict(r) for r in rows]


def get_history(limit=50):
    with _connect() as conn:
        rows = conn.execute("""
            SELECT s.id, s.title, s.created_at, s.updated_at
            FROM sessions s
            WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
            ORDER BY s.updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def add_uploaded_file(session_id, filename, file_type):
    with _connect() as conn:
        conn.execute("INSERT INTO uploaded_files(session_id,filename,file_type,created_at) VALUES(?,?,?,?)", (session_id, filename, file_type, now()))


def analytics():
    with _connect() as conn:
        total_questions = conn.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
        total_chats = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        voice_questions = conn.execute("SELECT COUNT(*) FROM messages WHERE role='user' AND input_type='voice'").fetchone()[0]
        files_uploaded = conn.execute("SELECT COUNT(*) FROM uploaded_files").fetchone()[0]
        domains = conn.execute("SELECT COALESCE(domain,'unknown') domain, COUNT(*) count FROM messages WHERE role='user' GROUP BY domain ORDER BY count DESC").fetchall()
        recent = conn.execute("SELECT title,updated_at FROM sessions ORDER BY updated_at DESC LIMIT 7").fetchall()
        return {
            "total_questions": total_questions,
            "total_chats": total_chats,
            "voice_questions": voice_questions,
            "files_uploaded": files_uploaded,
            "domains": [dict(r) for r in domains],
            "recent": [dict(r) for r in recent],
        }


def delete_session(session_id):
    with _connect() as conn:
        conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
