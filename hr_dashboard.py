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
import uuid
from streamlit_js_eval import get_session_storage_value, set_session_storage_value

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
# Data Handling
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

    normalized_user_name = user_name.strip().lower()
    df["ชื่อ-สกุล_normalized"] = df["ชื่อ-สกุล"].astype(str).str.strip().str.lower()
    
    df_user = df[df["ชื่อ-สกุล_normalized"] == normalized_user_name].copy()
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
# Firebase Integration
# -----------------------------
if not firebase_admin._apps:
    try:
        service_account_info = st.secrets["firebase"]
        firebase_config_dict = dict(service_account_info)
        cred = credentials.Certificate(firebase_config_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการเชื่อมต่อ Firebase: {e}")
        st.info("กรุณาตรวจสอบว่าคุณได้ตั้งค่า `secrets` บน Streamlit Cloud อย่างถูกต้อง")
        st.stop()

@st.cache_data(ttl=600)
def load_user_db():
    try:
        db = firestore.client()
        users_ref = db.collection("users")
        users_dict = {doc.id: doc.to_dict() for doc in users_ref.stream()}
        return users_dict
    except Exception as e:
        st.error(f"Error loading user database from Firestore: {e}")
        return {}

def save_user_db(phone, user_data):
    try:
        db = firestore.client()
        db.collection("users").document(phone).set(user_data)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Error saving user data to Firestore: {e}")

def create_session(user_phone):
    """Creates a new session in Firestore and returns its ID."""
    db = firestore.client()
    session_id = str(uuid.uuid4())
    session_ref = db.collection("sessions").document(session_id)
    session_ref.set({
        "user_phone": user_phone,
        "created_at": firestore.SERVER_TIMESTAMP
    })
    return session_id

def delete_session(session_id):
    """Deletes the current session from Firestore."""
    if session_id:
        db = firestore.client()
        db.collection("sessions").document(session_id).delete()

def logout():
    """Clears the session state and returns to the login page."""
    delete_session(st.session_state.get("session_id"))
    set_session_storage_value("session_id", None)
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

def check_session(session_id):
    """Checks for a valid session in Firestore."""
    if not session_id:
        return None
    db = firestore.client()
    session_ref = db.collection("sessions").document(session_id)
    session_doc = session_ref.get()
    if session_doc.exists:
        user_phone = session_doc.to_dict()["user_phone"]
        USERS_DB = load_user_db()
        if user_phone in USERS_DB:
            user_data = USERS_DB[user_phone]
            user_data["phone"] = user_phone
            return user_data
    return None

# -----------------------------
# Main App Logic
# -----------------------------
# --- Check for existing session at the start of every run ---
session_id_from_local_storage = get_session_storage_value(key="session_id")
if session_id_from_local_storage and "user" not in st.session_state:
    user_data = check_session(session_id_from_local_storage)
    if user_data:
        st.session_state.user = user_data["name"]
        st.session_state.phone = user_data["phone"]
        st.session_state.session_id = session_id_from_local_storage
        st.session_state.step = "dashboard"
    else:
        # Session in local storage is invalid, clear it
        set_session_storage_value("session_id", None)

if "step" not in st.session_state:
    st.session_state.step = "login"

if st.session_state.step == "login":
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
                max_chars=10,
                value=st.session_state.get("phone", "")
            )
            password = st.text_input(
                "รหัสผ่าน",
                type="password",
                placeholder="กรอกรหัสผ่าน"
            )

            if st.button("✅ เข้าสู่ระบบ", use_container_width=True, type="primary"):
                if phone in USERS_DB:
                    user_data = USERS_DB[phone]
                    if user_data.get("password") in ["null", None, ""]:
                        st.session_state.phone = phone
                        st.session_state.step = "set_password"
                        st.rerun()
                    elif user_data.get("password") and bcrypt.checkpw(password.encode('utf-8'), user_data.get("password").encode('utf-8')):
                        st.session_state.user = user_data["name"]
                        st.session_state.phone = phone
                        session_id = create_session(phone)
                        set_session_storage_value("session_id", session_id)
                        st.session_state.session_id = session_id
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

elif st.session_state.step == "set_password":
    USERS_DB = load_user_db()
    st.title(f"🔑 ตั้งรหัสผ่านครั้งแรก")
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            st.markdown(f"#### <div style='text-align: center;'>ตั้งรหัสผ่านครั้งแรก</div>", unsafe_allow_html=True)
            st.info(f"สำหรับเบอร์โทรศัพท์: {st.session_state.phone}")
            new_password = st.text_input("รหัสผ่านใหม่", type="password")
            confirm_password = st.text_input("ยืนยันรหัสผ่านใหม่", type="password")

            if st.button("💾 บันทึก", use_container_width=True, type="primary"):
                user_data = USERS_DB[st.session_state.phone]
                if not new_password:
                    st.error("รหัสผ่านใหม่ต้องไม่เป็นค่าว่าง")
                elif new_password != confirm_password:
                    st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน")
                else:
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    user_data["password"] = hashed_password
                    save_user_db(st.session_state.phone, user_data)
                    st.success("บันทึกรหัสผ่านใหม่เรียบร้อยแล้ว!")
                    st.session_state.step = "login"
                    st.rerun()
            if st.button("⬅️ กลับไปหน้าล็อกอิน", use_container_width=True):
                st.session_state.step = "login"
                st.rerun()

elif st.session_state.step == "change_password":
    USERS_DB = load_user_db()
    st.title(f"🔑 เปลี่ยนรหัสผ่าน")
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            st.markdown(f"#### <div style='text-align: center;'>เปลี่ยนรหัสผ่าน</div>", unsafe_allow_html=True)
            st.info(f"สำหรับเบอร์โทรศัพท์: {st.session_state.phone}")
            current_password = st.text_input("รหัสผ่านปัจจุบัน", type="password")
            new_password = st.text_input("รหัสผ่านใหม่", type="password")
            confirm_password = st.text_input("ยืนยันรหัสผ่านใหม่", type="password")

            if st.button("💾 บันทึก", use_container_width=True, type="primary"):
                user_data = USERS_DB[st.session_state.phone]
                if not bcrypt.checkpw(current_password.encode('utf-8'), user_data.get("password", "").encode('utf-8')):
                    st.error("รหัสผ่านปัจจุบันไม่ถูกต้อง")
                elif not new_password:
                    st.error("รหัสผ่านใหม่ต้องไม่เป็นค่าว่าง")
                elif new_password != confirm_password:
                    st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน")
                else:
                    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    user_data["password"] = hashed_password
                    save_user_db(st.session_state.phone, user_data)
                    st.success("บันทึกรหัสผ่านใหม่เรียบร้อยแล้ว!")
                    st.session_state.step = "dashboard"
                    st.rerun()
            if st.button("⬅️ กลับไปหน้าแดชบอร์ด", use_container_width=True):
                st.session_state.step = "dashboard"
                st.rerun()

elif st.session_state.step == "forgot_password":
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
                if user_phone not in USERS_DB:
                    st.error("ไม่พบเบอร์โทรศัพท์พนักงานนี้ในระบบ")
                elif admin_phone not in USERS_DB:
                    st.error("ไม่พบเบอร์โทรศัพท์ผู้ดูแลระบบในระบบ")
                else:
                    admin_data = USERS_DB[admin_phone]
                    if not bcrypt.checkpw(admin_password.encode('utf-8'), admin_data.get("password", "").encode('utf-8')):
                        st.error("รหัสผ่านผู้ดูแลระบบไม่ถูกต้อง")
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
        st.session_state.step = "login"
        st.rerun()

elif st.session_state.step == "dashboard":
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
        # Ensure the user can still log out if no data is found
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True, type="secondary")
    else:
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
        st.divider()
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True, type="secondary")


# -----------------------------
# Main App Logic
# -----------------------------
if "step" not in st.session_state:
    st.session_state.step = "login"

# Check if there's a valid session from local storage on every rerun
session_id_from_local_storage = st.session_state.get("session_id_hidden")
if session_id_from_local_storage:
    user_data = check_session(session_id_from_local_storage)
    if user_data:
        st.session_state.user = user_data["name"]
        st.session_state.phone = user_data["phone"]
        st.session_state.session_id = session_id_from_local_storage
        st.session_state.step = "dashboard"

if st.session_state.step == "login":
    display_login_page() # type: ignore
elif st.session_state.step == "set_password":
    display_password_page(mode="set") # type: ignore
elif st.session_state.step == "change_password":
    display_password_page(mode="change") # type: ignore
elif st.session_state.step == "forgot_password":
    display_forgot_password_page() # type: ignore
elif st.session_state.step == "dashboard":
    display_dashboard() # type: ignore
