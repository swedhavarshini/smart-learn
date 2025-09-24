import streamlit as st
import sqlite3
import pandas as pd
import hashlib

DB_PATH = "smartlearn.db"

# ========== DB Helpers ==========
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()

    # Questions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT UNIQUE,
        option_a TEXT,
        option_b TEXT,
        option_c TEXT,
        option_d TEXT,
        answer TEXT,
        subject TEXT,
        chapter TEXT,
        topic TEXT,
        difficulty TEXT,
        type TEXT
    );
    """)

    # Scores
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        question_id INTEGER,
        is_correct INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Reminders
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        weak_chapters TEXT,
        reminder_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT
    );
    """)
    conn.commit()
    conn.close()

def fetch_df(query, params=()):
    conn = get_conn()
    try:
        df = pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()
    return df

def execute(query, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    conn.close()

# ========== Authentication ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    if row:
        stored_hash, role = row
        if stored_hash == hash_password(password):
            return True, role
    return False, None

def seed_users():
    conn = get_conn()
    cur = conn.cursor()
    demo_users = [
        ("student1", hash_password("1234"), "student"),
        ("teacher1", hash_password("admin"), "teacher"),
    ]
    for u in demo_users:
        try:
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", u)
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()

# ========== Core Features ==========
def compute_weak_chapters(student_id, limit_chaps=3):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT q.chapter, SUM(s.is_correct) AS correct, COUNT(*) AS total
    FROM student_scores s
    JOIN questions q ON s.question_id = q.id
    WHERE s.student_id = ?
    GROUP BY q.chapter
    ORDER BY (1.0*SUM(s.is_correct)/COUNT(*)) ASC
    LIMIT ?
    """, (student_id, limit_chaps))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def save_reminder(student_id, weak_chapters, reminder_text):
    execute("INSERT INTO reminders (student_id, weak_chapters, reminder_text) VALUES (?, ?, ?)",
            (student_id, ",".join(weak_chapters), reminder_text))

# ---- Take Test ----
def take_test_ui(student_id, n_questions=5):
    st.header("Take Test")

    if "test_questions" not in st.session_state or st.session_state.get("test_student") != student_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, question, option_a, option_b, option_c, option_d, answer FROM questions ORDER BY RANDOM() LIMIT ?", (n_questions,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            st.warning("⚠️ No questions in DB. Add some first.")
            return

        st.session_state.test_questions = rows
        st.session_state.test_student = student_id
        st.session_state.answers = {r[0]: "" for r in rows}

    rows = st.session_state.test_questions
    for i, r in enumerate(rows, start=1):
        qid, qtext, a, b, c, d, ans = r
        st.markdown(f"**Q{i}. {qtext}**")
        choice = st.radio("", ("A","B","C","D"), key=f"q_{qid}")
        st.session_state.answers[qid] = choice

    if st.button("Submit Test"):
        conn = get_conn()
        cur = conn.cursor()
        correct_count = 0
        for qid, user_choice in st.session_state.answers.items():
            cur.execute("SELECT answer FROM questions WHERE id=?", (qid,))
            row = cur.fetchone()
            correct_ans = row[0].strip().upper()[0] if row and row[0] else ""
            is_correct = 1 if user_choice == correct_ans else 0
            if is_correct: correct_count += 1
            cur.execute("INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                        (student_id, qid, is_correct))
        conn.commit()
        conn.close()

        st.session_state.pop("test_questions", None)
        st.session_state.pop("test_student", None)
        st.session_state.pop("answers", None)

        total = len(rows)
        st.success(f"✅ Score: {correct_count}/{total} ({round(100*correct_count/total,2)}%)")

# ---- Adaptive Test ----
def adaptive_test_ui(student_id, n_questions=5):
    st.header("Adaptive Test")
    weak = compute_weak_chapters(student_id)
    if not weak:
        st.info("Take at least one test first.")
        return
    st.write("Weak chapters:", weak)

    placeholders = ",".join("?"*len(weak))
    query = f"SELECT id, question, option_a, option_b, option_c, option_d, answer FROM questions WHERE chapter IN ({placeholders}) ORDER BY RANDOM() LIMIT ?"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(query, tuple(weak)+(n_questions,))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        st.warning("No questions available in weak chapters.")
        return

    for i, r in enumerate(rows, start=1):
        qid, qtext, a, b, c, d, ans = r
        st.markdown(f"**Q{i}. {qtext}**")
        choice = st.radio("", ("A","B","C","D"), key=f"aq_{qid}")
        if st.button("Submit Adaptive Test", key=f"submit_{i}"):
            conn = get_conn()
            cur = conn.cursor()
            correct_ans = ans.strip().upper()[0] if ans else ""
            is_correct = 1 if choice == correct_ans else 0
            cur.execute("INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                        (student_id, qid, is_correct))
            conn.commit(); conn.close()
            st.success("Saved answer!")

# ---- Dashboard ----
def student_dashboard_ui(student_id):
    st.header(f"📊 Dashboard — {student_id}")
    df_overall = fetch_df("SELECT COUNT(*) AS attempted, SUM(is_correct) AS correct FROM student_scores WHERE student_id=?", (student_id,))
    if df_overall.empty or df_overall.at[0,"attempted"] == 0:
        st.info("No attempts yet.")
        return
    attempted = int(df_overall.at[0,"attempted"])
    correct = int(df_overall.at[0,"correct"] or 0)
    accuracy = round(100.0 * correct / attempted, 2)
    st.metric("Total Attempted", attempted)
    st.metric("Correct Answers", correct)
    st.metric("Accuracy (%)", accuracy)

# ---- Leaderboard ----
def leaderboard_ui():
    st.header("🏆 Leaderboard")
    df = fetch_df("""
        SELECT s.student_id AS student, COUNT(s.id) AS attempted, SUM(s.is_correct) AS correct,
               ROUND(100.0*SUM(s.is_correct)/COUNT(s.id),2) AS accuracy
        FROM student_scores s GROUP BY s.student_id ORDER BY accuracy DESC, attempted DESC
    """)
    if df.empty:
        st.info("No scores yet.")
    else:
        st.dataframe(df)

# ---- Reminders ----
def reminders_ui():
    st.header("🔔 Reminders")
    df = fetch_df("""
        SELECT s.student_id AS student, COUNT(s.id) AS attempted, SUM(s.is_correct) AS correct,
               ROUND(100.0*SUM(s.is_correct)/COUNT(s.id),2) AS accuracy
        FROM student_scores s GROUP BY s.student_id ORDER BY accuracy ASC, attempted DESC
    """)
    if df.empty:
        st.info("No students yet.")
        return
    for _, row in df.iterrows():
        sid = row['student']
        if st.button(f"Generate reminder for {sid}"):
            weak_chaps = compute_weak_chapters(sid)
            reminder_text = f"Please revise: {', '.join(weak_chaps)}"
            save_reminder(sid, weak_chaps, reminder_text)
            st.success(f"Reminder saved for {sid}")

# ---- Add Question ----
def add_question_ui():
    st.header("➕ Add Question")
    with st.form("add_q_form"):
        qtext = st.text_area("Question")
        opt_a = st.text_input("Option A")
        opt_b = st.text_input("Option B")
        opt_c = st.text_input("Option C")
        opt_d = st.text_input("Option D")
        answer = st.selectbox("Correct Answer", ("A","B","C","D"))
        subject = st.text_input("Subject")
        chapter = st.text_input("Chapter")
        topic = st.text_input("Topic")
        difficulty = st.selectbox("Difficulty", ("Easy","Medium","Hard"))
        qtype = st.text_input("Type")
        submitted = st.form_submit_button("Add")
        if submitted:
            execute("""
                INSERT OR IGNORE INTO questions
                (question, option_a, option_b, option_c, option_d, answer, subject, chapter, topic, difficulty, type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (qtext, opt_a, opt_b, opt_c, opt_d, answer, subject, chapter, topic, difficulty, qtype))
            st.success("✅ Question added.")

# ========== App ==========
st.set_page_config(page_title="SmartLearn AI", layout="wide")
ensure_tables()
seed_users()

# ---- Login ----
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user = None

if not st.session_state.logged_in:
    st.title("🔑 SmartLearn AI Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role = authenticate(username, password)
        if ok:
            st.session_state.logged_in = True
            st.session_state.user = username
            st.success(f"Welcome {username}")
            st.rerun()   # ✅ fixed
        else:
            st.error("❌ Invalid credentials")
    st.stop()

# ---- Sidebar ----
st.sidebar.header("Navigation")
student_id = st.session_state.user
st.sidebar.write(f"👤 Logged in as {student_id}")

options = ["Dashboard","Take Test","Adaptive Test","Leaderboard","Reminders","Add Question"]
action = st.sidebar.selectbox("Action", options)

# ---- Routing ----
if action == "Dashboard":
    student_dashboard_ui(student_id)
elif action == "Take Test":
    take_test_ui(student_id)
elif action == "Adaptive Test":
    adaptive_test_ui(student_id)
elif action == "Leaderboard":
    leaderboard_ui()
elif action == "Reminders":
    reminders_ui()
elif action == "Add Question":
    add_question_ui()
