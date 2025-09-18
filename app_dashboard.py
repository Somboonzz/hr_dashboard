import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os
import pytz
import time
import random

st.set_page_config(page_title="HR Dashboard", layout="wide")

# -----------------------------
# โซนเวลาไทย
# -----------------------------
bangkok_tz = pytz.timezone("Asia/Bangkok")

def thai_date(dt):
    return dt.strftime(f"%d/%m/{dt.year + 543}")

thai_months = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]

def format_thai_month(period):
    year = period.year + 543
    month = thai_months[period.month - 1]
    return f"{month} {year}"

# -----------------------------
# โหลด Excel
# -----------------------------
def load_data(file_path="attendances.xlsx"):
    try:
        if file_path and os.path.exists(file_path):
            df = pd.read_excel(file_path, engine='openpyxl')
            return df
        else:
            st.warning("❌ ไม่พบไฟล์ Excel: attendances.xlsx")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ อ่านไฟล์ Excel ไม่ได้: {e}")
        return pd.DataFrame()

df = load_data()

# -----------------------------
# Session State สำหรับ OTP + Login
# -----------------------------
if "step" not in st.session_state:
    st.session_state.step = "login"
if "phone" not in st.session_state:
    st.session_state.phone = None
if "otp" not in st.session_state:
    st.session_state.otp = None
if "user" not in st.session_state:
    st.session_state.user = None

# -----------------------------
# กำหนดผู้ใช้ (เบอร์ -> ชื่อ)
# -----------------------------
users = {
    "0989620358": "นายสมบูรณ์ เหนือกอง",
   
}

# -----------------------------
# หน้า Login
# -----------------------------
if st.session_state.step == "login":
    st.title("เข้าสู่ระบบ")
    phone_input = st.text_input("กรอกเบอร์โทรศัพท์")
    if st.button("ขอรหัส OTP"):
        if phone_input in users:
            st.session_state.phone = phone_input
            st.session_state.otp = str(random.randint(1000, 9999))
            st.session_state.step = "verify"
            st.success(f"รหัส OTP ของคุณคือ: {st.session_state.otp} (ทดสอบในแอพ)")
        else:
            st.error("ไม่พบผู้ใช้ในระบบ")
    st.stop()

# -----------------------------
# หน้า OTP
# -----------------------------
if st.session_state.step == "verify":
    st.title("ยืนยัน OTP")
    otp_input = st.text_input("กรอกรหัส OTP")
    if st.button("ยืนยัน"):
        if otp_input == st.session_state.otp:
            st.session_state.user = users[st.session_state.phone]
            st.session_state.step = "dashboard"
        else:
            st.error("รหัส OTP ไม่ถูกต้อง")
    st.stop()

# -----------------------------
# Dashboard (เฉพาะผู้ใช้)
# -----------------------------
if st.session_state.step == "dashboard":
    st.title(f"📊 แดชบอร์ดของ {st.session_state.user}")

    # Filter ข้อมูลเฉพาะผู้ใช้
    df_user = df[df["ชื่อ-สกุล"] == st.session_state.user].copy()

    if df_user.empty:
        st.info("ไม่มีข้อมูลให้แสดง")
        st.stop()

    # แก้ไขคอลัมน์
    for col in ["ชื่อ-สกุล", "แผนก", "ข้อยกเว้น"]:
        if col in df_user.columns:
            df_user[col] = df_user[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

    if "แผนก" in df_user.columns:
        df_user["แผนก"] = df_user["แผนก"].replace({"nan": "ไม่ระบุ", "": "ไม่ระบุ"})

    if "วันที่" in df_user.columns:
        df_user["วันที่"] = pd.to_datetime(df_user["วันที่"], errors='coerce')
        df_user["ปี"] = df_user["วันที่"].dt.year + 543
        df_user["เดือน"] = df_user["วันที่"].dt.to_period("M")

    # คำนวณประเภทการลา
    def leave_days(row):
        if "ครึ่งวัน" in str(row):
            return 0.5
        return 1

    df_user["ลาป่วย/ลากิจ"] = df_user["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"] else 0
    )
    df_user["ขาด"] = df_user["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ขาด", "ขาดครึ่งวัน"] else 0
    )
    df_user["สาย"] = df_user["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "สาย" else 0)
    df_user["พักผ่อน"] = df_user["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "พักผ่อน" else 0)

    leave_types = ["ลาป่วย/ลากิจ", "ขาด", "สาย", "พักผ่อน"]
    summary = df_user.groupby(["ชื่อ-สกุล", "แผนก"])[leave_types].sum().reset_index()

    st.markdown("### 📌 สรุปข้อมูลส่วนบุคคล")
    st.dataframe(summary.drop(columns=["ชื่อ-สกุล", "แผนก"], errors='ignore'), use_container_width=True)

    # -----------------------------
    # แสดงวันที่ของการลา/ขาด/สาย/พักผ่อน
    # -----------------------------
    for leave in leave_types:
        st.subheader(f"{leave}")
        if leave == "ลาป่วย/ลากิจ":
            relevant_exceptions = ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"]
        elif leave == "ขาด":
            relevant_exceptions = ["ขาด", "ขาดครึ่งวัน"]
        else:
            relevant_exceptions = [leave]

        dates = df_user.loc[df_user["ข้อยกเว้น"].isin(relevant_exceptions), ["วันที่", "ข้อยกเว้น"]]
        if not dates.empty:
            total_days = dates["ข้อยกเว้น"].apply(leave_days).sum()
            with st.expander(f"{leave} ({total_days} วัน)"):
                date_list = []
                for _, row in dates.iterrows():
                    label = row["วันที่"].strftime("%d/%m/%Y") + f" ({row['ข้อยกเว้น']})"
                    date_list.append(label)
                st.write(date_list)

        # กราฟ
        chart = (
            alt.Chart(summary)
            .mark_bar(cornerRadiusTopLeft=5, cornerRadiusBottomLeft=5, color="#C70039")
            .encode(
                y=alt.Y("ชื่อ-สกุล:N", sort="-x", title="ชื่อ-สกุล"),
                x=alt.X(leave + ":Q", title=leave),
                tooltip=["ชื่อ-สกุล", leave],
            )
            .properties(width=800, height=200)
        )
        st.altair_chart(chart, use_container_width=True)

    # -----------------------------
    # ปุ่มออกจากระบบ
    # -----------------------------
    if st.button("ออกจากระบบ"):
        st.session_state.step = "login"
        st.session_state.user = None
        st.session_state.otp = None
        st.session_state.phone = None
        st.experimental_rerun()
