import os
import sqlite3
import time

DEFAULT_DB_PATH = os.path.expanduser("~/.local/share/selfmod/selfmod.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL,
    start_time  REAL NOT NULL,
    end_time    REAL NOT NULL,
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_episodes_name ON episodes(name);

CREATE TABLE IF NOT EXISTS frames (
    id          INTEGER PRIMARY KEY,
    timestamp   REAL NOT NULL,
    content     TEXT NOT NULL,
    frame_type  TEXT NOT NULL CHECK(frame_type IN ('pre_change','post_change','periodic')),
    processed   INTEGER NOT NULL DEFAULT 0,
    summary     TEXT,
    episode_id  INTEGER REFERENCES episodes(id)
);

CREATE INDEX IF NOT EXISTS idx_frames_unprocessed ON frames(processed) WHERE processed = 0;
CREATE INDEX IF NOT EXISTS idx_frames_episode ON frames(episode_id);
CREATE INDEX IF NOT EXISTS idx_frames_timestamp ON frames(timestamp);
"""


MIGRATIONS = [
    # Add name column to episodes if missing
    ("episodes_name", """
        ALTER TABLE episodes ADD COLUMN name TEXT NOT NULL DEFAULT '';
    """),
]


def get_db(path=None):
    path = path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _run_migrations(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _run_migrations(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY)")
    applied = {r[0] for r in conn.execute("SELECT name FROM _migrations").fetchall()}
    for name, sql in MIGRATIONS:
        if name not in applied:
            try:
                conn.executescript(sql)
            except sqlite3.OperationalError:
                pass  # e.g. column already exists
            conn.execute("INSERT INTO _migrations (name) VALUES (?)", (name,))
    conn.commit()


def insert_frame(conn, timestamp, content, frame_type):
    cur = conn.execute(
        "INSERT INTO frames (timestamp, content, frame_type) VALUES (?, ?, ?)",
        (timestamp, content, frame_type),
    )
    conn.commit()
    return cur.lastrowid


def get_unprocessed_frames(conn, limit=20):
    return conn.execute(
        "SELECT * FROM frames WHERE processed = 0 ORDER BY timestamp LIMIT ?",
        (limit,),
    ).fetchall()


def update_frame_summary(conn, frame_id, summary, episode_id=None):
    conn.execute(
        "UPDATE frames SET summary = ?, episode_id = ?, processed = 1 WHERE id = ?",
        (summary, episode_id, frame_id),
    )


def insert_episode(conn, name, title, summary, start_time, end_time):
    cur = conn.execute(
        "INSERT INTO episodes (name, title, summary, start_time, end_time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name, title, summary, start_time, end_time, time.time()),
    )
    return cur.lastrowid


def update_episode(conn, episode_id, name=None, title=None, summary=None, end_time=None):
    if name is not None:
        conn.execute("UPDATE episodes SET name = ? WHERE id = ?", (name, episode_id))
    if title is not None:
        conn.execute("UPDATE episodes SET title = ? WHERE id = ?", (title, episode_id))
    if summary is not None:
        conn.execute("UPDATE episodes SET summary = ? WHERE id = ?", (summary, episode_id))
    if end_time is not None:
        conn.execute("UPDATE episodes SET end_time = ? WHERE id = ?", (end_time, episode_id))


def get_recent_episodes(conn, limit=10):
    return conn.execute(
        "SELECT * FROM episodes ORDER BY end_time DESC LIMIT ?",
        (limit,),
    ).fetchall()


def get_episode(conn, episode_id):
    return conn.execute(
        "SELECT * FROM episodes WHERE id = ?",
        (episode_id,),
    ).fetchone()


def resolve_episode(conn, id_or_name):
    """Look up episode by integer ID or by name."""
    try:
        return get_episode(conn, int(id_or_name))
    except (ValueError, TypeError):
        pass
    return conn.execute(
        "SELECT * FROM episodes WHERE name = ?",
        (id_or_name,),
    ).fetchone()


def rename_episode(conn, episode_id, new_name):
    conn.execute("UPDATE episodes SET name = ? WHERE id = ?", (new_name, episode_id))
    conn.commit()


def delete_episode(conn, episode_id):
    conn.execute("UPDATE frames SET episode_id = NULL WHERE episode_id = ?", (episode_id,))
    conn.execute("DELETE FROM episodes WHERE id = ?", (episode_id,))
    conn.commit()


def get_episode_frames(conn, episode_id):
    return conn.execute(
        "SELECT * FROM frames WHERE episode_id = ? ORDER BY timestamp",
        (episode_id,),
    ).fetchall()


def search_episodes(conn, query):
    pattern = f"%{query}%"
    return conn.execute(
        "SELECT * FROM episodes WHERE title LIKE ? OR summary LIKE ? ORDER BY start_time DESC",
        (pattern, pattern),
    ).fetchall()


def get_stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    unprocessed = conn.execute("SELECT COUNT(*) FROM frames WHERE processed = 0").fetchone()[0]
    episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    db_size = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else 0
    return {
        "total_frames": total,
        "unprocessed_frames": unprocessed,
        "episode_count": episodes,
        "db_size_mb": db_size / (1024 * 1024),
    }
