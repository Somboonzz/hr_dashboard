import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os
import pytz
import json

# -----------------------------
# การตั้งค่าหน้าเว็บและสไตล์
# -----------------------------
st.set_page_config(
    page_title="HR Dashboard",
    page_icon="📊",
    layout="wide"
)

# ซ่อน UI เริ่มต้นของ Streamlit
hide_streamlit_style = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# -----------------------------
# โซนเวลาและฟังก์ชันเกี่ยวกับวันที่
# -----------------------------
bangkok_tz = pytz.timezone("Asia/Bangkok")

def thai_date(dt):
    if pd.isna(dt):
        return "N/A"
    return dt.strftime(f"%d/%m/{dt.year + 543}")

def format_time(val):
    """คืนค่าเวลา HH:MM หรือ 00:00"""
    if pd.isna(val) or val in ["-", "", None]:
        return "00:00"
    try:
        if isinstance(val, datetime.time):
            return val.strftime("%H:%M")
        if isinstance(val, datetime.datetime):
            return val.strftime("%H:%M")
        parsed = pd.to_datetime(str(val), errors="coerce")
        if pd.isna(parsed):
            return "00:00"
        return parsed.strftime("%H:%M")
    except:
        return "00:00"

# -----------------------------
# การจัดการข้อมูล
# -----------------------------
@st.cache_data
def load_data(file_path="attendances.xlsx"):
    if file_path and os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            if 'วันที่' in df.columns:
                df['วันที่'] = pd.to_datetime(df['วันที่'], errors='coerce')

            def parse_time(val):
                if pd.isna(val) or val in ["-", "", None]:
                    return datetime.time(0, 0)
                try:
                    parsed = pd.to_datetime(str(val), format='%H:%M', errors='coerce')
                    if pd.isna(parsed):
                        return datetime.time(0, 0)
                    return parsed.time()
                except:
                    return datetime.time(0, 0)

            if 'เข้างาน' in df.columns:
                df['เข้างาน'] = df['เข้างาน'].apply(parse_time)
            if 'ออกงาน' in df.columns:
                df['ออกงาน'] = df['ออกงาน'].apply(parse_time)

            return df
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ Excel: {e}")
            return pd.DataFrame()
    else:
        st.warning("❌ ไม่พบไฟล์ Excel: attendances.xlsx")
        return pd.DataFrame()

def process_user_data(df, user_name):
    if df.empty or "ชื่อ-สกุล" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()

    df_user = df[df["ชื่อ-สกุล"] == user_name].copy()
    if df_user.empty:
        return pd.DataFrame(), pd.DataFrame()

    for col in ["ชื่อ-สกุล", "แผนก", "ข้อยกเว้น"]:
        if col in df_user.columns:
            df_user[col] = df_user[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    if "แผนก" in df_user.columns:
        df_user["แผนก"] = df_user["แผนก"].replace({"nan": "ไม่ระบุ", "": "ไม่ระบุ"})
    
    def leave_days(exception_text):
        return 0.5 if "ครึ่งวัน" in str(exception_text) else 1

    df_user["ลาป่วย/ลากิจ"] = df_user["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"] else 0)
    df_user["ขาด"] = df_user["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ขาด", "ขาดครึ่งวัน"] else 0)
    df_user["สาย"] = df_user["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "สาย" else 0)
    df_user["พักผ่อน"] = df_user["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "พักผ่อน" else 0)

    leave_types = ["ลาป่วย/ลากิจ", "ขาด", "สาย", "พักผ่อน"]
    summary_df = df_user.groupby("ชื่อ-สกุล")[leave_types].sum().reset_index()
    return df_user, summary_df

# -----------------------------
# การจัดการ Session State
# -----------------------------
def load_user_db():
    try:
        if os.path.exists("users_db.json"):
            with open("users_db.json", "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            initial_db = {
                "0989620358": {"name": "นายสมบูรณ์ เหนือกอง", "password": None},
                "0951646928": {"name": "นางสาวพรทิพย์ สุขอนันต์", "password": None},
                "0618741894": {"name": "นายอมร เพ็งโสภา", "password": None},
                "0888888888": {"name": "ผู้ดูแลระบบ", "password": "admin"},
            }
            with open("users_db.json", "w", encoding="utf-8") as f:
                json.dump(initial_db, f, indent=4)
            return initial_db
    except Exception as e:
        st.error(f"Error loading user database: {e}")
        return {}

def save_user_db():
    try:
        with open("users_db.json", "w", encoding="utf-8") as f:
            json.dump(st.session_state.USERS_DB, f, indent=4)
    except Exception as e:
        st.error(f"Error saving user database: {e}")

if "step" not in st.session_state:
    st.session_state.step = "login"
    st.session_state.phone = ""
    st.session_state.user = ""
    st.session_state.USERS_DB = load_user_db()

def logout():
    keys_to_reset = ["step", "phone", "user"]
    for key in keys_to_reset:
        if key in st.session_state:
            st.session_state[key] = ""
    st.session_state.step = "login"
    st.rerun()

# -----------------------------
# UI ส่วน Dashboard
# -----------------------------
def display_dashboard():
    with st.sidebar:
        st.header("เมนู")
        st.info(f"ยินดีต้อนรับ,\n**{st.session_state.user}**")
        st.divider()
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)

    st.header("📊 แดชบอร์ดสรุปข้อมูล")
    st.subheader(f"ของ **{st.session_state.user}**")

    df_full = load_data()
    df_user, summary = process_user_data(df_full, st.session_state.user)

    if summary.empty:
        st.info("ไม่พบข้อมูลการเข้า-ออกงานของคุณ")
        return

    st.markdown("### 🗓️ สรุปภาพรวม")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ลาป่วย/ลากิจ (วัน)", summary["ลาป่วย/ลากิจ"].sum())
    col2.metric("ขาดงาน (วัน)", summary["ขาด"].sum())
    col3.metric("มาสาย (ครั้ง)", int(summary["สาย"].sum()))
    col4.metric("วันพักผ่อน (วัน)", int(summary["พักผ่อน"].sum()))
    st.divider()

    st.markdown("### 📜 รายการวันที่")
    leave_types_map = {
        "ลาป่วย/ลากิจ": ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"],
        "ขาด": ["ขาด", "ขาดครึ่งวัน"],
        "สาย": ["สาย"],
        "พักผ่อน": ["พักผ่อน"]
    }
    
    for leave_type, exceptions in leave_types_map.items():
        dates_df = df_user[df_user["ข้อยกเว้น"].isin(exceptions)]
        total_days = df_user[leave_type].sum()
        if not dates_df.empty:
            with st.expander(f"ดูวันที่ **{leave_type}** (รวม {total_days} วัน/ครั้ง)"):
                for _, row in dates_df.sort_values(by="วันที่").iterrows():
                    check_in_time = format_time(row.get('เข้างาน'))
                    check_out_time = format_time(row.get('ออกงาน'))
                    time_display = f" {check_in_time}-{check_out_time}"

                    st.markdown(
                        f'<p style="font-size: 0.9rem; margin: 0;">- <b>{thai_date(row["วันที่"])}</b>{time_display} ({row["ข้อยกเว้น"]})</p>',
                        unsafe_allow_html=True
                    )

# -----------------------------
# Main App Logic
# -----------------------------
if st.session_state.step == "login":
    st.title("📊 HR Dashboard")
    st.info("หน้านี้เป็นตัวอย่าง login (ปรับให้เหมาะสมได้)")
    st.session_state.user = "นายสมบูรณ์ เหนือกอง"
    st.session_state.step = "dashboard"
    st.rerun()
else:
    display_dashboard()
