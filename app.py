import streamlit as st
import os
import sqlite3
import uuid
import time
import pandas as pd
from contextlib import closing
from io import BytesIO
import qrcode

# ==================================================
# CONFIG
# ==================================================
DB = "attendance_pro.db"
QR_REFRESH_SECONDS = 10
SESSION_VALIDITY = 300
ADMIN_PASSWORD = "a"   # change later

# ==================================================
# PAGE SETUP + THEME
# ==================================================
st.set_page_config(page_title="Smart Attendance System", layout="centered")

st.markdown("""
<style>
body { background:#F1F5F9; }
input, textarea {
    font-size: 18px !important;
    padding: 12px !important;
}

label {
    font-size: 18px !important;
    font-weight: 600;
}


.banner {
    background: linear-gradient(90deg,#1E3A8A,#2563EB);
    padding:30px;
    border-radius:20px;
    color:white;
    text-align:center;
    font-size:34px;
    font-weight:800;
    margin-bottom:30px;
}

.card {
    background:white;
    padding:30px;
    border-radius:20px;
    box-shadow:0 15px 35px rgba(0,0,0,0.12);
    margin-bottom:25px;
}

.big-btn button {
    width:100%;
    height:80px;
    font-size:24px !important;
    font-weight:800;
    border-radius:16px;
}

.sub-btn button {
    width:100%;
    height:55px;
    font-size:18px !important;
    border-radius:14px;
}
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='banner'>  Attendance System</div>", unsafe_allow_html=True)

# ==================================================
# DATABASE
# ==================================================
DEFAULT_PROGRAMS = ["MSc CS", "MSc DFIS", "MTech Cyber"]
DEFAULT_SUBJECTS = ["AI", "Blockchain", "Cyber Security", "Digital Forensics"]
DEFAULT_SEMESTERS = ["Sem 1", "Sem 2", "Sem 3", "Sem 4"]
DEFAULT_TIME_SLOTS = ["09:00–10:00", "10:00–11:00", "11:15–12:15"]
ENROLLMENT_FILE = "enrollment.xlsx"
CLASS_FILE = "class_details.xlsx"


def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with closing(conn()) as c:
        cur = c.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS students(
            id INTEGER PRIMARY KEY,
            name TEXT,
            enrollment TEXT UNIQUE,
            program TEXT,
            semester TEXT,
            device_id TEXT,
            device_info TEXT,
            registered_at INTEGER
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY,
            session_code TEXT,
            program TEXT,
            semester TEXT,
            subject TEXT,
            time_slot TEXT,
            expiry_ts INTEGER
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY,
            student_id INTEGER,
            session_id INTEGER,
            timestamp INTEGER,
            device_id TEXT,
            device_info TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS class_options(
            id INTEGER PRIMARY KEY,
            program TEXT,
            semester TEXT,
            subject TEXT,
            time_slot TEXT,
            source TEXT,
            UNIQUE(program, semester, subject, time_slot)
        )
        """)
        c.commit()

init_db()

if os.path.exists(ENROLLMENT_FILE) and not st.session_state.get("enrollment_loaded"):
    try:
        load_local_enrollments()
    except Exception:
        pass
    st.session_state.enrollment_loaded = True

# ==================================================
# HELPERS
# ==================================================
def now():
    return int(time.time())


def generate_code():
    return str(uuid.uuid4().int)[:6]


def generate_qr(data):
    qr = qrcode.QRCode(box_size=7, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def get_device_id():
    if "device_id" not in st.session_state:
        st.session_state.device_id = str(uuid.uuid4())
    return st.session_state.device_id


def get_device_info():
    if "device_info" not in st.session_state:
        st.session_state.device_info = "browser-session"
    return st.session_state.device_info


def load_students():
    with closing(conn()) as c:
        rows = c.execute("SELECT * FROM students ORDER BY enrollment").fetchall()
    return rows


def get_student_by_enrollment(enrollment):
    with closing(conn()) as c:
        return c.execute("SELECT * FROM students WHERE enrollment=?", (enrollment,)).fetchone()


def infer_sheet_defaults(sheet_name: str):
    lower = sheet_name.lower()
    program = ""
    semester = ""

    if "cyber" in lower:
        program = "MSc Cybersecurity"
    elif "forens" in lower or "inf sec" in lower or "digital" in lower:
        program = "Digital Forensics and Inf Sec"

    if "sem" in lower:
        import re
        m = re.search(r"sem(?:ester)?\s*([0-9]+)", lower)
        if m:
            semester = f"Sem {m.group(1)}"
    return program, semester


def save_roster_df(df, default_program="", default_semester=""):
    normalized = {col.strip().lower(): col for col in df.columns}
    required = ["name", "enrollment"]
    for key in required:
        if key not in normalized:
            raise ValueError(f"Roster file must include '{key}' column")

    program_col = normalized.get("program")
    semester_col = normalized.get("semester")
    imported = 0

    with closing(conn()) as c:
        cur = c.cursor()
        for _, row in df.iterrows():
            name = str(row.get(normalized["name"], "")).strip()
            enrollment = str(row.get(normalized["enrollment"], "")).strip()
            program = str(row.get(program_col, "")).strip() if program_col else ""
            semester = str(row.get(semester_col, "")).strip() if semester_col else ""
            if not program:
                program = default_program
            if not semester:
                semester = default_semester
            if not name or not enrollment:
                continue
            cur.execute("""
            INSERT INTO students(name,enrollment,program,semester,registered_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(enrollment) DO UPDATE SET
                name=excluded.name,
                program=excluded.program,
                semester=excluded.semester
            """, (name, enrollment, program, semester, now()))
            imported += 1
        c.commit()
    return imported


def save_roster_file(xls):
    total = 0
    summaries = []

    if isinstance(xls, dict):
        for sheet_name, df in xls.items():
            program, semester = infer_sheet_defaults(sheet_name)
            count = save_roster_df(df, program, semester)
            summaries.append((sheet_name, count, program, semester))
            total += count
    else:
        count = save_roster_df(xls)
        summaries.append(("Sheet", count, "", ""))
        total += count

    return total, summaries


def load_local_enrollments():
    if not os.path.exists(ENROLLMENT_FILE):
        return 0, []
    workbook = pd.read_excel(ENROLLMENT_FILE, sheet_name=None)
    return save_roster_file(workbook)


def load_class_options():
    with closing(conn()) as c:
        return c.execute("SELECT DISTINCT program, semester, subject, time_slot FROM class_options ORDER BY program, semester, subject, time_slot").fetchall()


def get_class_list(column):
    seen = []
    for row in load_class_options():
        value = row[column]
        if value and value not in seen:
            seen.append(value)
    return seen


def save_class_options_df(df):
    normalized = {col.strip().lower(): col for col in df.columns}
    required = ["program", "semester", "subject", "time_slot"]
    for key in required:
        if key not in normalized:
            raise ValueError(f"Class file must include '{key}' column")

    imported = 0
    with closing(conn()) as c:
        cur = c.cursor()
        for _, row in df.iterrows():
            program = str(row.get(normalized["program"], "")).strip()
            semester = str(row.get(normalized["semester"], "")).strip()
            subject = str(row.get(normalized["subject"], "")).strip()
            time_slot = str(row.get(normalized["time_slot"], "")).strip()
            if not program or not semester or not subject or not time_slot:
                continue
            cur.execute("""
            INSERT OR IGNORE INTO class_options(program,semester,subject,time_slot,source)
            VALUES(?,?,?,?,?)
            """, (program, semester, subject, time_slot, "admin_upload"))
            imported += cur.rowcount
        c.commit()
    return imported


def save_class_file(xls):
    total = 0
    summaries = []

    if isinstance(xls, dict):
        for sheet_name, df in xls.items():
            count = save_class_options_df(df)
            summaries.append((sheet_name, count))
            total += count
    else:
        count = save_class_options_df(xls)
        summaries.append(("Sheet", count))
        total += count

    return total, summaries

# ==================================================
# ROLE SELECTION
# ==================================================
if "role" not in st.session_state:
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🎓 Student", key="r_student"):
            st.session_state.role = "student"
            st.rerun()
    with c2:
        if st.button("👨‍🏫 Faculty", key="r_faculty"):
            st.session_state.role = "faculty"
            st.rerun()
    with c3:
        if st.button("🛠️ Admin", key="r_admin"):
            st.session_state.role = "admin"
            st.rerun()
    st.stop()

# ==================================================
# FACULTY PANEL
# ==================================================
if st.session_state.role == "faculty":
    st.markdown("<div class='card'><h2>👨‍🏫 Faculty Panel</h2></div>", unsafe_allow_html=True)

    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        program_choices = ["Add new program..."] + (get_class_list("program") or DEFAULT_PROGRAMS)
        program = st.selectbox("Program", program_choices)
        if program == "Add new program...":
            program = st.text_input("New Program", key="new_program")

        semester_choices = ["Add new semester..."] + (get_class_list("semester") or DEFAULT_SEMESTERS)
        semester = st.selectbox("Semester", semester_choices)
        if semester == "Add new semester...":
            semester = st.text_input("New Semester", key="new_semester")

        subject_choices = ["Add new subject..."] + (get_class_list("subject") or DEFAULT_SUBJECTS)
        subject = st.selectbox("Subject", subject_choices)
        if subject == "Add new subject...":
            subject = st.text_input("New Subject", key="new_subject")

        time_slot_choices = ["Add new slot..."] + (get_class_list("time_slot") or DEFAULT_TIME_SLOTS)
        time_slot = st.selectbox("Time Slot", time_slot_choices)
        if time_slot == "Add new slot...":
            time_slot = st.text_input("Custom Time Slot", key="new_time_slot")

        if st.button("▶ START ATTENDANCE SESSION", key="start_session"):
            if not program or not semester or not subject or not time_slot:
                st.error("Please fill all session details before starting.")
            else:
                code = generate_code()
                expiry = now() + SESSION_VALIDITY
                with closing(conn()) as c:
                    cur = c.cursor()
                    cur.execute("""
                    INSERT INTO sessions(session_code,program,semester,subject,time_slot,expiry_ts)
                    VALUES(?,?,?,?,?,?)
                    """, (code, program, semester, subject, time_slot, expiry))
                    c.commit()
                st.session_state.session_code = code
                st.session_state.session_start = now()
                st.success("Attendance session started.")

        st.markdown("</div>", unsafe_allow_html=True)

    if "session_code" in st.session_state:
        remaining = SESSION_VALIDITY - (now() - st.session_state.session_start)
        if remaining > 0:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.success("Session Active")
            st.markdown("### 🔢 SESSION CODE")
            st.code(st.session_state.session_code)

            qr_payload = f"?code={st.session_state.session_code}"
            img = generate_qr(qr_payload)
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            st.image(buf, width=300)
            st.info(f"Share this QR code or session code with students. Session expires in {remaining}s.")
            if st.button("End Session", key="end_session"):
                st.warning("Attendance session ended by faculty.")
                del st.session_state.session_code
                if "session_start" in st.session_state:
                    del st.session_state.session_start
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.warning("Session expired")
            del st.session_state.session_code
            if "session_start" in st.session_state:
                del st.session_state.session_start

# ==================================================
# STUDENT PANEL
# ==================================================
# ==================================================
# STUDENT PANEL (IMPROVED UI + CAMERA)
# ==================================================
if st.session_state.role == "student":
    st.markdown("<div class='card'><h2 style='font-size:28px;'>🎓 Student Attendance</h2></div>", unsafe_allow_html=True)

    params = st.query_params
    code_from_qr = params.get("code", [""])[0]
    device_id = get_device_id()
    device_info = get_device_info()

    if st.session_state.get("enrollment_loaded"):
        st.info(f"Enrollments from {ENROLLMENT_FILE} are loaded automatically.")

    students = load_students()
    roster_options = ["New student registration"] + [f"{row['enrollment']} | {row['name']}" for row in students]
    selected_from_roster = st.selectbox("Select your enrollment from the uploaded roster", roster_options, index=0)

    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("### 🧍 Student Details")

    if selected_from_roster != "New student registration":
        enrollment = selected_from_roster.split(" | ")[0]
        student = get_student_by_enrollment(enrollment)
        name = student["name"] if student else ""
        program = student["program"] if student else DEFAULT_PROGRAMS[0]
        semester = student["semester"] if student else DEFAULT_SEMESTERS[0]

        st.text_input("Full Name", value=name, disabled=True)
        st.text_input("Enrollment Number", value=enrollment, disabled=True)
        st.selectbox("Program", [program], index=0, disabled=True)
        st.selectbox("Semester", [semester], index=0, disabled=True)
    else:
        name = st.text_input("Full Name", key="s_name")
        enrollment = st.text_input("Enrollment Number", key="s_enroll")
        program = st.selectbox("Program", DEFAULT_PROGRAMS, key="s_prog")
        semester = st.selectbox("Semester", DEFAULT_SEMESTERS, key="s_sem")

    st.markdown("---")
    st.markdown("### 📷 Scan QR Code (Optional)")
    st.info("If QR scanning does not auto-fill, use the Session Code below.")
    camera_img = st.camera_input("Open Camera to scan QR", key="qr_camera")

    st.markdown("---")
    st.markdown("### 🔢 Session Code")

    session_code = st.text_input(
        "Enter Session Code (shown by faculty)",
        value=code_from_qr,
        key="s_code"
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("<div class='big-btn'>", unsafe_allow_html=True)
    submit = st.button("✅ SUBMIT ATTENDANCE", key="submit_att")
    st.markdown("</div>", unsafe_allow_html=True)

    if submit:
        if not enrollment or not session_code or not name:
            st.error("Please fill all required fields before submission.")
        else:
            with closing(conn()) as c:
                cur = c.cursor()
                cur.execute("SELECT * FROM students WHERE enrollment=?", (enrollment,))
                student_record = cur.fetchone()

                if student_record:
                    if student_record["device_id"] and student_record["device_id"] != device_id:
                        st.error("This student was registered from a different device. Please use the registered device or contact admin.")
                    else:
                        if not student_record["device_id"]:
                            cur.execute("""
                            UPDATE students
                            SET device_id=?, device_info=?, registered_at=?
                            WHERE id=?
                            """, (device_id, device_info, now(), student_record["id"]))
                            c.commit()
                        student_id = student_record["id"]
                else:
                    cur.execute("""
                    INSERT INTO students(name,enrollment,program,semester,device_id,device_info,registered_at)
                    VALUES(?,?,?,?,?,?,?)
                    """, (name, enrollment, program, semester, device_id, device_info, now()))
                    student_id = cur.lastrowid
                    c.commit()

                cur.execute("""
                SELECT * FROM sessions
                WHERE session_code=? AND expiry_ts>=?
                """, (session_code, now()))
                sess = cur.fetchone()

                if not sess:
                    st.error("❌ Invalid or expired session")
                else:
                    cur.execute("""
                    SELECT 1 FROM attendance
                    WHERE student_id=? AND session_id=?
                    """, (student_id, sess["id"]))

                    if cur.fetchone():
                        st.warning("⚠ Attendance already marked")
                    else:
                        cur.execute("""
                        INSERT INTO attendance(student_id,session_id,timestamp,device_id,device_info)
                        VALUES(?,?,?,?,?)
                        """, (student_id, sess["id"], now(), device_id, device_info))
                        c.commit()
                        st.success("🎉 Attendance Recorded Successfully!")

    st.markdown("</div>", unsafe_allow_html=True)

# ==================================================
# ADMIN PANEL
# ==================================================
if st.session_state.role == "admin":
    st.markdown("<div class='card'><h2>🛠️ Admin Panel</h2></div>", unsafe_allow_html=True)

    pwd = st.text_input("Admin Password", type="password")
    if pwd != ADMIN_PASSWORD:
        st.warning("Enter admin password")
        st.stop()

    st.markdown("### 📥 Upload Student Roster")
    st.info("Upload an Excel file with one or more sheets. Each sheet should include name and enrollment. Optional program and semester columns are also supported.")
    roster_file = st.file_uploader("Upload roster Excel", type=["xlsx", "xls"], key="roster_upload")
    if roster_file is not None:
        try:
            workbook = pd.read_excel(roster_file, sheet_name=None)
            total, summaries = save_roster_file(workbook)
            st.success(f"Uploaded {total} student enrollments from {len(summaries)} sheet(s).")
            for sheet_name, count, program, semester in summaries:
                details = []
                if program:
                    details.append(f"program={program}")
                if semester:
                    details.append(f"semester={semester}")
                extra = f" ({', '.join(details)})" if details else ""
                st.write(f"- {sheet_name}: {count} rows{extra}")
        except Exception as e:
            st.error(f"Failed to upload roster: {e}")

    st.markdown("### 📥 Upload Class Details")
    st.info("Upload an Excel file with columns: program, semester, subject, time_slot. Multiple sheets are supported.")
    class_file = st.file_uploader("Upload class details Excel", type=["xlsx", "xls"], key="class_upload")
    if class_file is not None:
        try:
            workbook = pd.read_excel(class_file, sheet_name=None)
            total, summaries = save_class_file(workbook)
            st.success(f"Uploaded {total} class rows from {len(summaries)} sheet(s).")
            for sheet_name, count in summaries:
                st.write(f"- {sheet_name}: {count} rows")
        except Exception as e:
            st.error(f"Failed to upload class details: {e}")

    student_rows = load_students()
    class_rows = load_class_options()
    if student_rows:
        st.markdown("### 📋 Uploaded Student Roster")
        student_df = pd.DataFrame(student_rows)
        student_df = student_df[["name", "enrollment", "program", "semester", "registered_at"]]
        student_df = student_df.rename(columns={"registered_at": "registered_at_unix"})
        st.dataframe(student_df, use_container_width=True)

    if class_rows:
        st.markdown("### 🧑‍🏫 Uploaded Class Options")
        class_df = pd.DataFrame(class_rows)
        class_df = class_df[["program", "semester", "subject", "time_slot"]]
        st.dataframe(class_df, use_container_width=True)

    st.markdown("### 🧾 Attendance Records")
    with closing(conn()) as c:
        df = pd.read_sql_query("""
        SELECT s.name, s.enrollment, s.program, s.semester,
               se.subject, se.time_slot,
               datetime(a.timestamp,'unixepoch') as time,
               a.device_id, a.device_info
        FROM attendance a
        JOIN students s ON a.student_id=s.id
        JOIN sessions se ON a.session_id=se.id
        ORDER BY time DESC
        """, c)

    st.dataframe(df, use_container_width=True)

    if not df.empty:
        output = BytesIO()
        try:
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
        except Exception:
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False)
        output.seek(0)

        st.download_button(
            "⬇ DOWNLOAD ATTENDANCE EXCEL",
            data=output,
            file_name="attendance.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
