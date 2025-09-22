import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os
import pytz
import json
import firebase_admin
from firebase_admin import credentials, firestore
import bcrypt

# -----------------------------
# Page Setup and Styling
# -----------------------------
st.set_page_config(
    page_title="HR Dashboard",
    page_icon="📊",
    layout="wide"
)

# Hide default Streamlit UI
hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# -----------------------------
# Timezone and Date Functions
# -----------------------------
bangkok_tz = pytz.timezone("Asia/Bangkok")

def thai_date(dt):
    """Converts a datetime object to a Thai date string (Buddhist year)."""
    if pd.isna(dt):
        return "N/A"
    return dt.strftime(f"%d/%m/{dt.year + 543}")

def format_time(dt):
    """Converts a datetime object to a time string (HH:MM)."""
    if pd.isna(dt) or (isinstance(dt, datetime.time) and dt == datetime.time(0, 0)):
        return "00:00"
    return dt.strftime("%H:%M")

# -----------------------------
# Data Handling (load_data and process_user_data remain unchanged)
# -----------------------------
@st.cache_data
def load_data(file_path="attendances.xlsx"):
    """Loads data from an Excel or CSV file and returns a DataFrame."""
    file_extension = os.path.splitext(file_path)[1].lower()
    
    if not os.path.exists(file_path):
        st.warning(f"❌ Data file not found: {file_path}")
        return pd.DataFrame()

    try:
        if file_extension in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path, engine='openpyxl')
        elif file_extension == '.csv':
            df = pd.read_csv(file_path)
        else:
            st.error(f"Unsupported file format: {file_extension}")
            return pd.DataFrame()
        
        # Data cleaning and type conversion
        if 'วันที่' in df.columns:
            df['วันที่'] = pd.to_datetime(df['วันที่'], errors='coerce')
        if 'เข้างาน' in df.columns:
            df['เข้างาน'] = df['เข้างาน'].replace('-', None)
            df['เข้างาน'] = pd.to_datetime(df['เข้างาน'], format='%H:%M:%S', errors='coerce').dt.time
        if 'ออกงาน' in df.columns:
            df['ออกงาน'] = df['ออกงาน'].replace('-', None)
            df['ออกงาน'] = pd.to_datetime(df['ออกงาน'], format='%H:%M:%S', errors='coerce').dt.time

        return df
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return pd.DataFrame()

def process_user_data(df, user_name):
    """Processes attendance data for a specific user."""
    if df.empty or "ชื่อ-สกุล" not in df.columns:
        return pd.DataFrame(), pd.DataFrame()

    # Normalize user name from Firebase
    normalized_user_name = user_name.strip().lower()

    # Normalize names in the DataFrame for comparison
    df["ชื่อ-สกุล_normalized"] = df["ชื่อ-สกุล"].astype(str).str.strip().str.lower()
    
    # Filter the DataFrame using the normalized names
    df_user = df[df["ชื่อ-สกุล_normalized"] == normalized_user_name].copy()
    if df_user.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Clean up string columns
    for col in ["ชื่อ-สกุล", "แผนก", "ข้อยกเว้น"]:
        if col in df_user.columns:
            df_user[col] = df_user[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    if "แผนก" in df_user.columns:
        df_user["แผนก"] = df_user["แผนก"].replace({"nan": "ไม่ระบุ", "": "ไม่ระบุ"})
    
    # Calculate leave days
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
# Firebase Integration
# -----------------------------

# Initialize Firebase (run only once)
if not firebase_admin._apps:
    try:
        # Load the secrets object from Streamlit
        service_account_info = st.secrets["firebase"]
        
        # Convert the Streamlit object to a standard Python dictionary
        # This is a robust way to handle the object from st.secrets
        firebase_config_dict = dict(service_account_info)
        
        # Now pass the standard dictionary to credentials.Certificate
        cred = credentials.Certificate(firebase_config_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ Firebase: {e}")
        st.info("กรุณาตรวจสอบว่าคุณได้ตั้งค่า `secrets` บน Streamlit Cloud อย่างถูกต้อง")
        st.stop()

def load_user_db():
    """Loads the user database from Firestore."""
    try:
        db = firestore.client()
        users_ref = db.collection("users")
        users_dict = {}
        for doc in users_ref.stream():
            users_dict[doc.id] = doc.to_dict()
        return users_dict
    except Exception as e:
        st.error(f"Error loading user database from Firestore: {e}")
        return {}

def save_user_db(phone, user_data):
    """Saves a single user's data to Firestore for improved efficiency."""
    try:
        db = firestore.client()
        db.collection("users").document(phone).set(user_data)
    except Exception as e:
        st.error(f"Error saving user data to Firestore: {e}")

# Initialize session state
if "step" not in st.session_state:
    st.session_state.step = "login"
    st.session_state.phone = ""
    st.session_state.user = ""

def logout():
    """Clears the session state and returns to the login page."""
    for key in list(st.session_state.keys()):
        if key not in ['firebase_config_dict']:
            del st.session_state[key]
    st.session_state.step = "login"
    st.rerun()

# -----------------------------
# UI Display Functions
# -----------------------------

def display_login_page():
    """Displays the login form."""
    USERS_DB = load_user_db()
    st.title("📊 HR Dashboard")
    st.markdown("กรุณาเข้าสู่ระบบเพื่อดูข้อมูลการเข้า-ออกงานของคุณ")

    col1, col2, col3 = st.columns([1, 1.5, 1])

    with col2:
        with st.container(border=True):
            st.markdown("#### <div style='text-align: center;'>เข้าสู่ระบบ</div>", unsafe_allow_html=True)
            
            phone = st.text_input(
                "เบอร์โทรศัพท์",
                placeholder="กรอกเบอร์โทรศัพท์ 10 หลัก",
                max_chars=10
            )
            password = st.text_input(
                "รหัสผ่าน",
                type="password",
                placeholder="กรอกรหัสผ่าน"
            )

            if st.button("✅ เข้าสู่ระบบ", use_container_width=True, type="primary"):
                if phone in USERS_DB:
                    user_data = USERS_DB[phone]
                    # Check for "null" string, None, or empty string before proceeding
                    if user_data.get("password") in ["null", None, ""]:
                        st.session_state.phone = phone
                        st.session_state.step = "set_password"
                        st.rerun()
                    # Now it's safe to check the password with bcrypt
                    elif bcrypt.checkpw(password.encode('utf-8'), user_data.get("password").encode('utf-8')):
                        st.session_state.user = user_data["name"]
                        st.session_state.phone = phone
                        st.session_state.step = "dashboard"
                        st.rerun()
                    else:
                        st.error("รหัสผ่านไม่ถูกต้อง")
                else:
                    st.error("ไม่พบเบอร์โทรศัพท์นี้ในระบบ")

            st.markdown("---")
            if st.button("🔒 ลืมรหัสผ่าน", use_container_width=True):
                st.session_state.step = "forgot_password"
                st.rerun()
                
def display_password_page(mode="set"):
    """Displays the page for setting or changing a password."""
    USERS_DB = load_user_db()
    title_map = {"set": "ตั้งรหัสผ่านครั้งแรก", "change": "เปลี่ยนรหัสผ่าน"}
    title = title_map.get(mode, "จัดการรหัสผ่าน")
    st.title(f"🔑 {title}")

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            st.markdown(f"#### <div style='text-align: center;'>{title}</div>", unsafe_allow_html=True)
            st.info(f"สำหรับเบอร์โทรศัพท์: {st.session_state.phone}")

            if mode == "change":
                current_password = st.text_input("รหัสผ่านปัจจุบัน", type="password")
            
            new_password = st.text_input("รหัสผ่านใหม่", type="password")
            confirm_password = st.text_input("ยืนยันรหัสผ่านใหม่", type="password")

            if st.button("💾 บันทึก", use_container_width=True, type="primary"):
                user_data = USERS_DB[st.session_state.phone]
                
                # Check current password only in change mode
                if mode == "change" and not bcrypt.checkpw(current_password.encode('utf-8'), user_data.get("password").encode('utf-8')):
                    st.error("รหัสผ่านปัจจุบันไม่ถูกต้อง")
                elif not new_password:
                    st.error("รหัสผ่านใหม่ต้องไม่เป็นค่าว่าง")
                elif new_password != confirm_password:
                    st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน")
                else:
                    # Hash the new password before saving
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    user_data["password"] = hashed_password
                    save_user_db(st.session_state.phone, user_data)
                    st.success("บันทึกรหัสผ่านใหม่เรียบร้อยแล้ว!")
                    if mode == "change":
                        st.session_state.step = "dashboard"
                    else: # mode == "set"
                        st.session_state.step = "login"
                    st.rerun()
                
            if mode == "set":
                if st.button("⬅️ กลับไปหน้าล็อกอิน", use_container_width=True):
                    logout()
            else:
                if st.button("⬅️ กลับไปหน้าแดชบอร์ด", use_container_width=True):
                    st.session_state.step = "dashboard"
                    st.rerun()

def display_forgot_password_page():
    """Displays the page for password reset with admin verification."""
    USERS_DB = load_user_db()
    st.title("🔒 ลืมรหัสผ่าน")
    st.markdown("กรุณาให้ผู้ดูแลระบบช่วยเหลือในการรีเซ็ตรหัสผ่าน")

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            st.markdown("#### <div style='text-align: center;'>รีเซ็ตรหัสผ่าน</div>", unsafe_allow_html=True)
            
            user_phone = st.text_input(
                "เบอร์โทรศัพท์พนักงานที่ลืมรหัส", 
                placeholder="กรอกเบอร์โทรศัพท์ 10 หลัก", 
                max_chars=10
            )
            admin_phone = st.text_input(
                "เบอร์โทรศัพท์ผู้ดูแลระบบ", 
                placeholder="กรอกเบอร์โทรศัพท์ผู้ดูแลระบบ", 
                max_chars=10
            )
            admin_password = st.text_input(
                "รหัสผ่านผู้ดูแลระบบ", 
                type="password",
                placeholder="กรอกรหัสผ่านผู้ดูแลระบบ"
            )
            new_password = st.text_input("รหัสผ่านใหม่", type="password", key="new_password")
            confirm_password = st.text_input("ยืนยันรหัสผ่านใหม่", type="password", key="confirm_new_password")

            if st.button("💾 บันทึกรหัสผ่านใหม่", use_container_width=True, type="primary"):
                # Check if the user to be reset exists
                if user_phone not in USERS_DB:
                    st.error("ไม่พบเบอร์โทรศัพท์พนักงานนี้ในระบบ")
                # Check if the admin exists and get their data
                elif admin_phone not in USERS_DB:
                    st.error("ไม่พบเบอร์โทรศัพท์ผู้ดูแลระบบในระบบ")
                else:
                    admin_data = USERS_DB[admin_phone]
                    # Check admin password
                    if not bcrypt.checkpw(admin_password.encode('utf-8'), admin_data.get("password", "").encode('utf-8')):
                        st.error("รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง")
                    # Validate new password
                    elif not new_password or new_password != confirm_password:
                        st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน หรือเป็นค่าว่าง")
                    else:
                        hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        USERS_DB[user_phone]["password"] = hashed_password
                        save_user_db(user_phone, USERS_DB[user_phone])
                        st.success("ตั้งรหัสผ่านใหม่สำเร็จแล้ว! กรุณากลับไปหน้าล็อกอิน")
                        st.session_state.step = "login"
                        st.rerun()

    if st.button("⬅️ กลับไปหน้าล็อกอิน", use_container_width=True):
        logout()


def display_dashboard():
    """Displays the user's dashboard."""
    with st.sidebar:
        st.header("เมนู")
        st.info(f"ยินดีต้อนรับ,\n**{st.session_state.user}**")
        
        if st.button("🔑 เปลี่ยนรหัสผ่าน"):
            st.session_state.step = "change_password"
            st.rerun()
        
        st.divider()
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)

    st.header("📊 แดชบอร์ดสรุปข้อมูล")
    st.subheader(f"**{st.session_state.user}**")

    df_full = load_data()

    if not df_full.empty and 'วันที่' in df_full.columns:
        df_full_cleaned = df_full.dropna(subset=['วันที่'])
        if not df_full_cleaned.empty:
            start_date = df_full_cleaned['วันที่'].min()
            end_date = df_full_cleaned['วันที่'].max()
            st.markdown(
                f'<p style="font-size: 0.8rem; margin: 0;">ข้อมูลระหว่างวันที่: <b>{thai_date(start_date)}</b> ถึง <b>{thai_date(end_date)}</b></p>',
                unsafe_allow_html=True
            )
    st.divider()

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

    st.markdown("### 📈 รายละเอียดและสถิติ")
    summary_melted = summary.melt(
        id_vars=["ชื่อ-สกุล"],
        value_vars=["ลาป่วย/ลากิจ", "ขาด", "สาย", "พักผ่อน"],
        var_name="ประเภท",
        value_name="จำนวนวัน/ครั้ง"
    )
    chart = alt.Chart(summary_melted).mark_bar().encode(
        x=alt.X('จำนวนวัน/ครั้ง:Q', title='จำนวน (วัน/ครั้ง)'),
        y=alt.Y('ประเภท:N', title='ประเภท', sort='-x'),
        color=alt.Color('ประเภท:N', 
                         scale=alt.Scale(
                             domain=['ลาป่วย/ลากิจ', 'ขาด', 'สาย', 'พักผ่อน'],
                             range=['#FFC300', '#C70039', '#FF5733', '#33C1FF']
                         ),
                         legend=None),
        tooltip=['ประเภท', 'จำนวนวัน/ครั้ง']
    ).properties(title='กราฟเปรียบเทียบข้อมูล')
    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### 📜 รายการวันที่")
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
                    time_display = f' <span style="white-space: nowrap;">{check_in_time}-{check_out_time}</span>'

                    st.markdown(
                        f'<p style="font-size: 0.9rem; margin: 0;">- <b>{thai_date(row["วันที่"])}</b>{time_display} ({row["ข้อยกเว้น"]})</p>',
                        unsafe_allow_html=True
                    )

# -----------------------------
# Main App Logic
# -----------------------------
if st.session_state.step == "login":
    display_login_page()
elif st.session_state.step == "set_password":
    display_password_page(mode="set")
elif st.session_state.step == "change_password":
    display_password_page(mode="change")
elif st.session_state.step == "forgot_password":
    display_forgot_password_page()
elif st.session_state.step == "dashboard":
    display_dashboard()
else:
    display_login_page()
