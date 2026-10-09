import sqlite3
from datetime import datetime

DATABASE_FILE = "moderation.db"


def get_connection():
    return sqlite3.connect(DATABASE_FILE)


def setup_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            violations INTEGER DEFAULT 0,
            last_violation TEXT
        )
    """)

    conn.commit()
    conn.close()


def add_violation(user_id, username, score):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO users (
            user_id,
            username,
            score,
            violations,
            last_violation
        )
        VALUES (?, ?, ?, 1, ?)

        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            score = score + excluded.score,
            violations = violations + 1,
            last_violation = excluded.last_violation
    """, (
        str(user_id),
        username,
        score,
        datetime.now().isoformat()
    ))

    conn.commit()

    cursor.execute("""
        SELECT score, violations
        FROM users
        WHERE user_id = ?
    """, (str(user_id),))

    result = cursor.fetchone()

    conn.close()

    return result


def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, username, score, violations, last_violation
        FROM users
        WHERE user_id = ?
    """, (str(user_id),))

    result = cursor.fetchone()

    conn.close()

    return result


def reset_score(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE users
        SET score = 0,
            violations = 0,
            last_violation = NULL
        WHERE user_id = ?
    """, (str(user_id),))

    changed = cursor.rowcount

    conn.commit()
    conn.close()

    return changed > 0