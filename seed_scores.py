# seed_scores.py
import sqlite3, random, os, sys

DB = "smartlearn.db"
if not os.path.exists(DB):
    print("Error: smartlearn.db not found in this folder.")
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Ensure student_scores table exists
cur.execute("""
CREATE TABLE IF NOT EXISTS student_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT,
  question_id INTEGER,
  is_correct INTEGER,
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")
conn.commit()

cur.execute("SELECT id FROM questions")
rows = cur.fetchall()
ids = [r[0] for r in rows]
if not ids:
    print("No questions found. Run import_questions.py first to populate questions.")
    conn.close()
    raise SystemExit(1)

students = ["student_1","student_2","student_3"]
for s in students:
    for _ in range(8):  # each student attempts 8 random questions
        qid = random.choice(ids)
        is_correct = random.choice([0,1,1])  # bias slightly towards correct
        cur.execute("INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                    (s, qid, is_correct))
conn.commit()
print("Seeded sample student_scores for demo students:", students)
conn.close()
