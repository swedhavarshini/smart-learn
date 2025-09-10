"""
import_questions.py

Usage (Windows CMD / PowerShell):
  python import_questions.py
  OR
  python import_questions.py MyQuestions.xlsx

Requirements:
  pip install pandas openpyxl
"""

import sqlite3
import pandas as pd
import sys
import os

DB_PATH = "smartlearn.db"
DEFAULT_XLSX = "SmartLearn_Effective50.xlsx"

def ensure_table(conn):
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
    conn.commit()

def load_excel(xlsx_path):
    # Read Excel into DataFrame; expect header columns matching:
    # Question, Option A, Option B, Option C, Option D, Answer, Subject, Chapter, Topic, Difficulty, Type
    df = pd.read_excel(xlsx_path, engine="openpyxl")
    # Normalize column names (strip, lower)
    df.columns = [c.strip() for c in df.columns]
    expected = ["Question","Option A","Option B","Option C","Option D","Answer","Subject","Chapter","Topic","Difficulty","Type"]
    # If headers vary slightly (like option_a), attempt tolerant mapping:
    cols_map = {}
    for e in expected:
        for actual in df.columns:
            if actual.lower().replace("_"," ").replace("-", " ") == e.lower().replace("_"," ").replace("-", " "):
                cols_map[e] = actual
                break
    # If some expected missing, try common alternatives
    alt_map = {
        "Option A": ["OptionA","A","opt a","opt_a","option_a"],
        "Option B": ["OptionB","B","opt b","opt_b","option_b"],
        "Option C": ["OptionC","C","opt c","opt_c","option_c"],
        "Option D": ["OptionD","D","opt d","opt_d","option_d"],
        "Answer": ["Ans","Correct Answer","Correct","answer_key","answer_option"],
        "Question": ["Q","Question Text","question_text"],
        "Subject": ["subject"],
        "Chapter": ["chapter"],
        "Topic": ["topic"],
        "Difficulty": ["difficulty"],
        "Type": ["type"]
    }
    for e in expected:
        if e not in cols_map:
            for alt in alt_map.get(e, []):
                for actual in df.columns:
                    if actual.lower().replace("_"," ").replace("-", " ") == alt.lower().replace("_"," ").replace("-", " "):
                        cols_map[e] = actual
                        break
                if e in cols_map:
                    break

    missing = [e for e in expected if e not in cols_map]
    if missing:
        print("Warning: Excel missing columns:", missing)
        print("Found columns:", list(df.columns))
        # continue with best-effort; fill missing with empty strings
        for m in missing:
            df[m] = ""

    # Build DataFrame with expected column order
    ordered_df = pd.DataFrame()
    for e in expected:
        ordered_df[e] = df[cols_map[e]] if e in cols_map else df.get(e, "")

    # Clean whitespace & convert answer to single-letter (A/B/C/D) where possible
    ordered_df = ordered_df.fillna("")
    ordered_df["Answer"] = ordered_df["Answer"].astype(str).str.strip()
    # If answers are full options like "5 m/s^2", convert to letter by comparing to options
    def normalize_answer(row):
        ans = row["Answer"].strip()
        opts = [str(row["Option A"]).strip(), str(row["Option B"]).strip(), str(row["Option C"]).strip(), str(row["Option D"]).strip()]
        if not ans:
            return ""
        # If ans is single letter already
        if len(ans) == 1 and ans.upper() in ("A","B","C","D"):
            return ans.upper()
        # Try to match text to option
        for i,opt in enumerate(opts):
            if ans.lower() == opt.lower():
                return ["A","B","C","D"][i]
        # fallback: if answer contains option letter
        for ch in ans.upper():
            if ch in ("A","B","C","D"):
                return ch
        return ans  # leave as-is
    ordered_df["Answer"] = ordered_df.apply(normalize_answer, axis=1)
    # Rename columns to DB fields
    ordered_df = ordered_df.rename(columns={
        "Question":"question",
        "Option A":"option_a","Option B":"option_b","Option C":"option_c","Option D":"option_d",
        "Answer":"answer","Subject":"subject","Chapter":"chapter","Topic":"topic",
        "Difficulty":"difficulty","Type":"type"
    })
    return ordered_df

def import_to_db(df, conn):
    cur = conn.cursor()
    inserted = 0
    skipped = 0
    for _, row in df.iterrows():
        vals = (
            str(row.get("question","")).strip(),
            str(row.get("option_a","")).strip(),
            str(row.get("option_b","")).strip(),
            str(row.get("option_c","")).strip(),
            str(row.get("option_d","")).strip(),
            str(row.get("answer","")).strip(),
            str(row.get("subject","")).strip(),
            str(row.get("chapter","")).strip(),
            str(row.get("topic","")).strip(),
            str(row.get("difficulty","")).strip(),
            str(row.get("type","")).strip()
        )
        if not vals[0]:
            skipped += 1
            continue
        try:
            cur.execute("""
            INSERT INTO questions (question, option_a, option_b, option_c, option_d,
                                   answer, subject, chapter, topic, difficulty, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, vals)
            inserted += 1
        except sqlite3.IntegrityError:
            # unique constraint on question — skip duplicates
            skipped += 1
        except Exception as e:
            print("Error inserting row:", e)
            skipped += 1
    conn.commit()
    return inserted, skipped

def main():
    # choose excel path
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    if not os.path.exists(xlsx):
        print(f"File not found: {xlsx}")
        print("Place the Excel file in the script folder or pass the filename as an argument.")
        return

    # connect DB and ensure table
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)

    print("Reading Excel:", xlsx)
    df = load_excel(xlsx)
    print("Rows to import:", len(df))
    ins, skip = import_to_db(df, conn)
    print(f"Done. Inserted: {ins}, Skipped (duplicates/blank): {skip}")

    # show counts
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM questions")
    total = cur.fetchone()[0]
    print("Total questions in DB now:", total)
    conn.close()

if __name__ == "__main__":
    main()
