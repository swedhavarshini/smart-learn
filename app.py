import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# ========== Config ==========
DB_PATH = "smartlearn.db"

# ========== DB helpers ==========
def get_conn():
    # check_same_thread=False because Streamlit can call functions multiple times
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def ensure_tables():
    conn = get_conn()
    cur = conn.cursor()
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS student_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        question_id INTEGER,
        is_correct INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        weak_chapters TEXT,
        reminder_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        return cur
    finally:
        conn.close()

# ensure DB tables exist
ensure_tables()

# ========== Utility functions ==========
def compute_weak_chapters(student_id, limit_chaps=3):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT q.chapter, SUM(s.is_correct) AS correct, COUNT(*) AS total
    FROM student_scores s
    JOIN questions q ON s.question_id = q.id
    WHERE s.student_id = ?
    GROUP BY q.chapter
    HAVING COUNT(*) > 0
    ORDER BY (1.0*SUM(s.is_correct)/COUNT(*)) ASC
    LIMIT ?
    """, (student_id, limit_chaps))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def save_reminder(student_id, weak_chapters, reminder_text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO reminders (student_id, weak_chapters, reminder_text) VALUES (?, ?, ?)",
                (student_id, ",".join(weak_chapters), reminder_text))
    conn.commit()
    conn.close()

# ========== UI helper: take test ==========
def take_test_ui(student_id, n_questions=10):
    st.header("Take Test (Random Questions)")

    # prepare test only if not present or for different student
    if "test_questions" not in st.session_state or st.session_state.get("test_student") != student_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, question, option_a, option_b, option_c, option_d, answer FROM questions ORDER BY RANDOM() LIMIT ?",
                    (n_questions,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            st.warning("No questions found in the database. Use 'Add Question' or run import script.")
            return

        st.session_state.test_questions = rows
        st.session_state.test_student = student_id
        st.session_state.answers = {r[0]: "" for r in rows}

    rows = st.session_state.test_questions

    # render questions
    for i, r in enumerate(rows, start=1):
        qid, qtext, a, b, c, d, ans = r
        st.markdown(f"**Q{i}. {qtext}**")
        choice = st.radio("", ("A", "B", "C", "D"), key=f"q_{qid}")
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
            if is_correct:
                correct_count += 1
            cur.execute("INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                        (student_id, qid, is_correct))
        conn.commit()
        conn.close()

        # clear session state for test
        st.session_state.pop("test_questions", None)
        st.session_state.pop("test_student", None)
        st.session_state.pop("answers", None)

        total = len(rows)
        st.success(f"Test submitted — Score: {correct_count}/{total} ({round(100*correct_count/total,2)}%)")

        # show chapter-wise performance for this test
        qids_tuple = tuple([r[0] for r in rows])
        placeholders = ",".join("?"*len(qids_tuple))
        query = f"""
            SELECT q.chapter, SUM(s.is_correct) as correct, COUNT(*) as total
            FROM student_scores s JOIN questions q ON s.question_id = q.id
            WHERE s.student_id=? AND s.question_id IN ({placeholders})
            GROUP BY q.chapter
            """
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(query, (student_id,)+qids_tuple)
        chap_rows = cur.fetchall()
        conn.close()
        if chap_rows:
            st.subheader("Performance by chapter for this test")
            for chap, c, t in chap_rows:
                st.write(f"- **{chap}**: {c}/{t} correct ({round(100*c/t,2)}%)")

# ========== UI: Adaptive test ==========
def adaptive_test_ui(student_id, n_questions=5):
    st.header("Adaptive Test (from weakest chapters)")
    # compute weak chapters
    weak = compute_weak_chapters(student_id, limit_chaps=3)
    if not weak:
        st.info("No history yet — take a regular test first.")
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
        st.warning("No questions found in those chapters.")
        return

    # reuse session state mechanism to hold adaptive test
    key = f"adaptive_{student_id}"
    if key not in st.session_state:
        st.session_state[key] = {"rows": rows, "answers": {r[0]: "" for r in rows}}

    for i, r in enumerate(st.session_state[key]["rows"], start=1):
        qid, qtext, a, b, c, d, ans = r
        st.markdown(f"**Q{i}. {qtext}**")
        choice = st.radio("", ("A","B","C","D"), key=f"aq_{qid}")
        st.session_state[key]["answers"][qid] = choice

    if st.button("Submit Adaptive Test"):
        conn = get_conn()
        cur = conn.cursor()
        correct_count = 0
        for qid, user_choice in st.session_state[key]["answers"].items():
            cur.execute("SELECT answer FROM questions WHERE id=?", (qid,))
            row = cur.fetchone()
            correct_ans = row[0].strip().upper()[0] if row and row[0] else ""
            is_correct = 1 if user_choice == correct_ans else 0
            if is_correct:
                correct_count += 1
            cur.execute("INSERT INTO student_scores (student_id, question_id, is_correct) VALUES (?, ?, ?)",
                        (student_id, qid, is_correct))
        conn.commit()
        conn.close()

        # clear
        st.session_state.pop(key, None)
        total = len(rows)
        st.success(f"Adaptive Test submitted — Score: {correct_count}/{total} ({round(100*correct_count/total,2)}%)")

# ========== UI: Dashboard ==========
def student_dashboard_ui(student_id):
    st.header(f"Dashboard — {student_id}")
    df_overall = fetch_df("SELECT COUNT(*) AS attempted, SUM(is_correct) AS correct FROM student_scores WHERE student_id=?", (student_id,))
    if df_overall.empty or df_overall.at[0,"attempted"] == 0:
        st.info("No attempts yet. Take a test to generate your report.")
        return
    attempted = int(df_overall.at[0,"attempted"])
    correct = int(df_overall.at[0,"correct"] or 0)
    accuracy = round(100.0 * correct / attempted, 2) if attempted else 0
    st.metric("Total Attempted", attempted)
    st.metric("Correct Answers", correct)
    st.metric("Accuracy (%)", accuracy)

    # subject-wise
    subj = fetch_df("""
        SELECT q.subject, SUM(s.is_correct) as correct, COUNT(*) as total
        FROM student_scores s JOIN questions q ON s.question_id=q.id
        WHERE s.student_id=?
        GROUP BY q.subject
    """, (student_id,))
    if not subj.empty:
        subj["accuracy"] = (subj["correct"] / subj["total"] * 100).round(2)
        st.subheader("Subject-wise performance")
        st.dataframe(subj[["subject","correct","total","accuracy"]])

    # weakest chapters
    weak = fetch_df("""
        SELECT q.chapter, SUM(s.is_correct) as correct, COUNT(*) as total
        FROM student_scores s JOIN questions q ON s.question_id=q.id
        WHERE s.student_id=?
        GROUP BY q.chapter
        ORDER BY (1.0*SUM(s.is_correct)/COUNT(*)) ASC
        LIMIT 5
    """, (student_id,))
    if not weak.empty:
        weak["accuracy"] = (weak["correct"] / weak["total"] * 100).round(2)
        st.subheader("Weakest Chapters")
        st.table(weak[["chapter","correct","total","accuracy"]])

    # accuracy trend (cumulative)
    rows = fetch_df("SELECT id, is_correct FROM student_scores WHERE student_id=? ORDER BY id", (student_id,))
    if not rows.empty:
        cum = rows["is_correct"].expanding().mean()*100
        st.subheader("Accuracy trend (cumulative)")
        st.line_chart(cum)

# ========== UI: Leaderboard ==========
def leaderboard_ui():
    st.header("Leaderboard")
    df = fetch_df("""
        SELECT s.student_id AS student, COUNT(s.id) AS attempted, SUM(s.is_correct) AS correct,
               ROUND(100.0*SUM(s.is_correct)/COUNT(s.id),2) AS accuracy
        FROM student_scores s
        GROUP BY s.student_id
        ORDER BY accuracy DESC, attempted DESC
    """)
    if df.empty:
        st.info("No student data yet.")
        return
    st.dataframe(df)

# ========== UI: Reminders ==========
def reminders_ui():
    st.header("Reminders (Simulated)")
    # list students by ascending accuracy (need attention first)
    df = fetch_df("""
        SELECT s.student_id AS student, COUNT(s.id) AS attempted, SUM(s.is_correct) AS correct,
               ROUND(100.0*SUM(s.is_correct)/COUNT(s.id),2) AS accuracy
        FROM student_scores s GROUP BY s.student_id ORDER BY accuracy ASC, attempted DESC
    """)
    if df.empty:
        st.info("No student data yet.")
        return
    for idx, row in df.iterrows():
        sid = row['student']
        st.write(f"**{sid}** — Accuracy: {row['accuracy']}% — Attempted: {row['attempted']}")
        if st.button(f"Generate reminder for {sid}", key=f"rem_{sid}"):
            weak_chaps = compute_weak_chapters(sid, limit_chaps=3)
            if not weak_chaps:
                st.write("No history to generate reminder.")
            else:
                reminder_text = f"Please revise: {', '.join(weak_chaps)}. Recommended: take adaptive tests this week."
                save_reminder(sid, weak_chaps, reminder_text)
                st.success(f"Reminder saved for {sid}: {', '.join(weak_chaps)}")

    # Show saved reminders
    st.subheader("Saved reminders")
    rem_df = fetch_df("SELECT student_id, weak_chapters, reminder_text, created_at FROM reminders ORDER BY created_at DESC LIMIT 50")
    if rem_df.empty:
        st.write("No reminders saved yet.")
    else:
        st.dataframe(rem_df)

# ========== UI: Add question (admin) ==========
def add_question_ui():
    st.header("Add Question (Admin)")
    with st.form("add_q_form"):
        qtext = st.text_area("Question")
        col1, col2 = st.columns(2)
        with col1:
            opt_a = st.text_input("Option A")
            opt_b = st.text_input("Option B")
            opt_c = st.text_input("Option C")
        with col2:
            opt_d = st.text_input("Option D")
            answer = st.selectbox("Correct option", ("A","B","C","D"))
            subject = st.text_input("Subject", value="Physics")
        chapter = st.text_input("Chapter", value="")
        topic = st.text_input("Topic", value="")
        difficulty = st.selectbox("Difficulty", ("Easy","Medium","Hard"))
        qtype = st.selectbox("Type", ("Conceptual","Numerical","Formula","Mixed"))
        submitted = st.form_submit_button("Add Question")
        if submitted:
            if not qtext.strip():
                st.error("Question text cannot be empty.")
            else:
                # compute answer text from chosen letter
                opts = {"A": opt_a, "B": opt_b, "C": opt_c, "D": opt_d}
                correct_text = opts.get(answer, "").strip()
                conn = get_conn()
                cur = conn.cursor()
                try:
                    cur.execute("""
                    INSERT INTO questions (question, option_a, option_b, option_c, option_d, answer, subject, chapter, topic, difficulty, type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (qtext.strip(), opt_a.strip(), opt_b.strip(), opt_c.strip(), opt_d.strip(),
                          answer.strip(), subject.strip(), chapter.strip(), topic.strip(), difficulty, qtype))
                    conn.commit()
                    st.success("Question added.")
                except sqlite3.IntegrityError:
                    st.warning("This question already exists (duplicate skipped).")
                finally:
                    conn.close()

# ========== Streamlit app layout ==========
st.set_page_config(page_title="SmartLearn AI", layout="wide")
st.title("SmartLearn AI — Mini Dashboard")

# Sidebar
st.sidebar.header("Student / Actions")
student_id = st.sidebar.text_input("Student ID", value="student_1")
action = st.sidebar.selectbox("Action", ["Dashboard", "Take Test", "Adaptive Test", "Leaderboard", "Reminders", "Add Question"])

# Main area - route actions
if action == "Dashboard":
    student_dashboard_ui(student_id)

elif action == "Take Test":
    n = st.sidebar.number_input("Number of questions", min_value=1, max_value=20, value=5)
    take_test_ui(student_id, n_questions=n)

elif action == "Adaptive Test":
    n = st.sidebar.number_input("Adaptive test size", min_value=1, max_value=20, value=5, key="adaptive_n")
    adaptive_test_ui(student_id, n_questions=n)

elif action == "Leaderboard":
    leaderboard_ui()

elif action == "Reminders":
    reminders_ui()

elif action == "Add Question":
    add_question_ui()

# Footer: quick DB info
try:
    info_df = fetch_df("SELECT COUNT(*) as total_questions FROM questions")
    total_q = int(info_df.at[0,"total_questions"]) if not info_df.empty else 0
    st.sidebar.markdown(f"**Questions:** {total_q}")
except Exception:
    pass
