import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title="Python Beginners Attendance", layout="centered")

st.title("📋 Python Beginners Attendance")
st.markdown("Please fill in your details to mark attendance for the session.")

# File to store attendance
FILENAME = "attendance.csv"

# Load or create the CSV file
if not os.path.exists(FILENAME):
    df = pd.DataFrame(columns=["Name", "Email", "Organization/College", "Program/Sem/Position"])
    df.to_csv(FILENAME, index=False)
else:
    df = pd.read_csv(FILENAME)

# Form
with st.form("attendance_form"):
    name = st.text_input("Full Name")
    email = st.text_input("Email")
    org = st.text_input("Organization / College")
    role = st.text_input("Program / Semester / Position")
    submitted = st.form_submit_button("Submit Attendance")

    if submitted:
        if not name or not email or not org or not role:
            st.warning("❗ Please fill all fields.")
        elif email.lower() in df["Email"].str.lower().values:
            st.info("✅ Attendance already marked for this email.")
        else:
            new_entry = pd.DataFrame([{
                "Name": name,
                "Email": email,
                "Organization/College": org,
                "Program/Sem/Position": role
            }])
            df = pd.concat([df, new_entry], ignore_index=True)
            df.to_csv(FILENAME, index=False)
            st.success("✅ Attendance marked successfully. Thank you!")

# Optional: Display current number of attendees
st.markdown(f"### 📊 Total Attendance Count: `{len(df)}`")
