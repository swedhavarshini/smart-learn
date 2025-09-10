# check_db.py
import sqlite3
import os

DB = "smartlearn.db"
if not os.path.exists(DB):
    print(f"Database file not found: {DB}")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cur.fetchall()]
print("Tables in DB:", tables)

if "questions" in tables:
    cur.execute("SELECT COUNT(*) FROM questions")
    print("Questions:", cur.fetchone()[0])
else:
    print("questions table is missing.")

if "student_scores" in tables:
    cur.execute("SELECT COUNT(*) FROM student_scores")
    print("student_scores rows:", cur.fetchone()[0])
else:
    print("student_scores table is missing.")

if "reminders" in tables:
    cur.execute("SELECT COUNT(*) FROM reminders")
    print("reminders rows:", cur.fetchone()[0])
else:
    print("reminders table is missing.")

cur.close()
conn.close()
