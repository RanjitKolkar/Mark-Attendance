import streamlit as st
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

st.markdown("<div class='banner'>📘 Smart Attendance System</div>", unsafe_allow_html=True)

# ==================================================
# DATABASE
# ==================================================
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
            semester TEXT
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
            timestamp INTEGER
        )
        """)
        c.commit()

init_db()

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

        program = st.selectbox("Program", ["MSc CS", "MSc DFIS", "MTech Cyber"])
        semester = st.selectbox("Semester", ["Sem 1", "Sem 2", "Sem 3", "Sem 4"])
        subject = st.selectbox("Subject", ["AI", "Blockchain", "Cyber Security", "Digital Forensics"])
        time_slot = st.selectbox("Time Slot", ["09:00–10:00", "10:00–11:00", "11:15–12:15"])

        if st.button("▶ START ATTENDANCE SESSION", key="start_session"):
            code = generate_code()
            expiry = now() + SESSION_VALIDITY
            with closing(conn()) as c:
                cur = c.cursor()
                cur.execute("""
                INSERT INTO sessions(session_code,program,semester,subject,time_slot,expiry_ts)
                VALUES(?,?,?,?,?,?)
                """,(code,program,semester,subject,time_slot,expiry))
                c.commit()
            st.session_state.session_code = code
            st.session_state.session_start = now()

        st.markdown("</div>", unsafe_allow_html=True)

    if "session_code" in st.session_state:
        remaining = SESSION_VALIDITY - (now() - st.session_state.session_start)
        if remaining > 0:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.success("Session Active")
            st.markdown("### 🔢 SESSION CODE")
            st.code(st.session_state.session_code)

            refresh_id = int(now() / QR_REFRESH_SECONDS)
            qr_payload = f"?code={st.session_state.session_code}&r={refresh_id}"
            img = generate_qr(qr_payload)
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)

            st.image(buf, width=300)
            st.info(f"QR refreshes every {QR_REFRESH_SECONDS} seconds | ⏳ {remaining}s left")
            st.markdown("</div>", unsafe_allow_html=True)

            time.sleep(1)
            st.rerun()
        else:
            st.warning("Session expired")
            del st.session_state.session_code

# ==================================================
# STUDENT PANEL
# ==================================================
# ==================================================
# STUDENT PANEL (IMPROVED UI + CAMERA)
# ==================================================
if st.session_state.role == "student":
    st.markdown("<div class='card'><h2 style='font-size:28px;'>🎓 Student Attendance</h2></div>", unsafe_allow_html=True)

    params = st.experimental_get_query_params()
    code_from_qr = params.get("code", [""])[0]

    with st.container():
        st.markdown("<div class='card'>", unsafe_allow_html=True)

        st.markdown("### 🧍 Student Details")

        name = st.text_input("Full Name", key="s_name")
        enrollment = st.text_input("Enrollment Number", key="s_enroll")

        program = st.selectbox(
            "Program",
            ["MSc CS", "MSc DFIS", "MTech Cyber"],
            key="s_prog"
        )

        semester = st.selectbox(
            "Semester",
            ["Sem 1", "Sem 2", "Sem 3", "Sem 4"],
            key="s_sem"
        )

        st.markdown("---")
        st.markdown("### 📷 Scan QR Code (Optional)")

        st.info("If QR scanning does not auto-fill, use Session Code below.")

        camera_img = st.camera_input(
            "Open Camera to scan QR",
            key="qr_camera"
        )

        st.markdown("---")
        st.markdown("### 🔢 Session Code")

        session_code = st.text_input(
            "Enter Session Code (shown by faculty)",
            value=code_from_qr,
            key="s_code"
        )

        st.markdown("<br>", unsafe_allow_html=True)

        st.markdown(
            "<div class='big-btn'>",
            unsafe_allow_html=True
        )
        submit = st.button("✅ SUBMIT ATTENDANCE", key="submit_att")
        st.markdown("</div>", unsafe_allow_html=True)

        if submit:
            if not name or not enrollment or not session_code:
                st.error("Please fill all required fields")
            else:
                with closing(conn()) as c:
                    cur = c.cursor()

                    # Student registration
                    cur.execute("SELECT * FROM students WHERE enrollment=?", (enrollment,))
                    s = cur.fetchone()
                    if not s:
                        cur.execute("""
                        INSERT INTO students(name,enrollment,program,semester)
                        VALUES(?,?,?,?)
                        """, (name, enrollment, program, semester))
                        student_id = cur.lastrowid
                    else:
                        student_id = s["id"]

                    # Validate session
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
                            INSERT INTO attendance(student_id,session_id,timestamp)
                            VALUES(?,?,?)
                            """, (student_id, sess["id"], now()))
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

    with closing(conn()) as c:
        df = pd.read_sql_query("""
        SELECT s.name, s.enrollment, s.program, s.semester,
               se.subject, se.time_slot,
               datetime(a.timestamp,'unixepoch') as time
        FROM attendance a
        JOIN students s ON a.student_id=s.id
        JOIN sessions se ON a.session_id=se.id
        ORDER BY time DESC
        """, c)

    st.dataframe(df, use_container_width=True)

    if not df.empty:
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        output.seek(0)

        st.download_button(
            "⬇ DOWNLOAD ATTENDANCE EXCEL",
            data=output,
            file_name="attendance.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
