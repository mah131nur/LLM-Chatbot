import json
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
            user_id TEXT,
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
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            age INTEGER,
            studies TEXT,
            university TEXT,
            interests TEXT
        );
        """)
        # Lightweight migration for anyone with an older database file
        # that doesn't have the user_id column yet (added later than
        # the original schema). Safe to run repeatedly — ignored once
        # the column already exists.
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT")
        except sqlite3.OperationalError:
            pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# CHAT SESSIONS — all scoped to a user_id so different visitors
# never see each other's conversations, matching how ChatGPT
# keeps each account's chat history private.
# ============================================================

def create_session(user_id, title="New Chat"):
    stamp = now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO sessions(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (user_id, title, stamp, stamp),
        )
        return cur.lastrowid


def session_belongs_to_user(session_id, user_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)
        ).fetchone()
        return row is not None


def add_message(session_id, role, content, domain=None, input_type="text"):
    stamp = now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages(session_id,role,content,domain,input_type,created_at) VALUES(?,?,?,?,?,?)",
            (session_id, role, content, domain, input_type, stamp),
        )
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (stamp, session_id))


def set_title_if_new(session_id, title):
    title = (title or "New Chat").strip().replace("\n", " ")[:70]
    if not title:
        return
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=? AND title='New Chat'",
            (title, now(), session_id),
        )


def get_session_messages(session_id, user_id=None):
    """If user_id is given, only returns messages when that user
    actually owns this session — prevents one visitor from reading
    another visitor's chat by guessing/incrementing a session id."""
    if user_id is not None and not session_belongs_to_user(session_id, user_id):
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role,content,domain,input_type,created_at FROM messages WHERE session_id=? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_history(user_id, limit=50):
    with _connect() as conn:
        rows = conn.execute("""
            SELECT s.id, s.title, s.created_at, s.updated_at
            FROM sessions s
            WHERE s.user_id = ?
              AND EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
            ORDER BY s.updated_at DESC
            LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in rows]


def delete_session(session_id, user_id):
    """Only deletes the session if it actually belongs to this user."""
    with _connect() as conn:
        conn.execute(
            "DELETE FROM messages WHERE session_id=? AND session_id IN "
            "(SELECT id FROM sessions WHERE id=? AND user_id=?)",
            (session_id, session_id, user_id),
        )
        conn.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id))


def add_uploaded_file(session_id, filename, file_type):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO uploaded_files(session_id,filename,file_type,created_at) VALUES(?,?,?,?)",
            (session_id, filename, file_type, now()),
        )


def analytics(user_id):
    with _connect() as conn:
        total_questions = conn.execute(
            "SELECT COUNT(*) FROM messages m JOIN sessions s ON m.session_id=s.id "
            "WHERE m.role='user' AND s.user_id=?", (user_id,)
        ).fetchone()[0]
        total_chats = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?", (user_id,)
        ).fetchone()[0]
        voice_questions = conn.execute(
            "SELECT COUNT(*) FROM messages m JOIN sessions s ON m.session_id=s.id "
            "WHERE m.role='user' AND m.input_type='voice' AND s.user_id=?", (user_id,)
        ).fetchone()[0]
        files_uploaded = conn.execute(
            "SELECT COUNT(*) FROM uploaded_files f JOIN sessions s ON f.session_id=s.id "
            "WHERE s.user_id=?", (user_id,)
        ).fetchone()[0]
        domains = conn.execute(
            "SELECT COALESCE(m.domain,'unknown') domain, COUNT(*) count "
            "FROM messages m JOIN sessions s ON m.session_id=s.id "
            "WHERE m.role='user' AND s.user_id=? GROUP BY domain ORDER BY count DESC",
            (user_id,)
        ).fetchall()
        recent = conn.execute(
            "SELECT title,updated_at FROM sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 7",
            (user_id,)
        ).fetchall()
        return {
            "total_questions": total_questions,
            "total_chats": total_chats,
            "voice_questions": voice_questions,
            "files_uploaded": files_uploaded,
            "domains": [dict(r) for r in domains],
            "recent": [dict(r) for r in recent],
        }


# ============================================================
# PROFILES — one row per anonymous user_id, so each browser's
# saved name/age/studies/etc. is private to that browser only.
# ============================================================

def get_profile(user_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return {}
        profile = dict(row)
        profile.pop("user_id", None)
        raw_interests = profile.get("interests")
        try:
            profile["interests"] = json.loads(raw_interests) if raw_interests else []
        except (TypeError, ValueError):
            profile["interests"] = []
        return {k: v for k, v in profile.items() if v not in (None, "", [])}


def save_profile(user_id, profile):
    interests = profile.get("interests") or []
    if not isinstance(interests, list):
        interests = []
    with _connect() as conn:
        conn.execute("""
            INSERT INTO profiles(user_id, name, age, studies, university, interests)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                studies=excluded.studies,
                university=excluded.university,
                interests=excluded.interests
        """, (
            user_id,
            profile.get("name"),
            profile.get("age"),
            profile.get("studies"),
            profile.get("university"),
            json.dumps(interests),
        ))
