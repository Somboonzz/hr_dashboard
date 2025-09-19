import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os
import pytz
import random
import json

# -----------------------------
# การตั้งค่าหน้าเว็บและสไตล์
# -----------------------------
st.set_page_config(
    page_title="HR Dashboard",
    page_icon="📊",
    layout="wide"
)

# ซ่อน UI เริ่มต้นของ Streamlit เพื่อให้ดูเป็นแอปฯ มากขึ้น
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
    """แปลง datetime object เป็นสตริงวันที่ไทย (พ.ศ.)"""
    if pd.isna(dt):
        return "N/A"
    return dt.strftime(f"%d/%m/{dt.year + 543}")

def format_time(dt):
    """แปลง datetime object เป็นสตริงเวลา (ชม.:นาที)"""
    if pd.isna(dt):
        return "N/A"
    return dt.strftime("%H:%M")

# -----------------------------
# การจัดการข้อมูล
# -----------------------------
@st.cache_data
def load_data(file_path="attendances.xlsx"):
    """โหลดข้อมูลจากไฟล์ Excel และคืนค่าเป็น DataFrame"""
    if file_path and os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
            if 'วันที่' in df.columns:
                df['วันที่'] = pd.to_datetime(df['วันที่'], errors='coerce')
            if 'เข้างาน' in df.columns:
                df['เข้างาน'] = pd.to_datetime(df['เข้างาน'], errors='coerce').dt.time
            if 'ออกงาน' in df.columns:
                df['ออกงาน'] = pd.to_datetime(df['ออกงาน'], errors='coerce').dt.time
            return df
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการอ่านไฟล์ Excel: {e}")
            return pd.DataFrame()
    else:
        st.warning("❌ ไม่พบไฟล์ Excel: attendances.xlsx")
        return pd.DataFrame()

def process_user_data(df, user_name):
    """ประมวลผลข้อมูลสำหรับผู้ใช้ที่ระบุ"""
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
# การจัดการ Session State และ Authentication
# -----------------------------
def load_user_db():
    """โหลดฐานข้อมูลผู้ใช้จากไฟล์ JSON ถ้ามี"""
    try:
        if os.path.exists("users_db.json"):
            with open("users_db.json", "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # ใช้ข้อมูลตัวอย่างและบันทึกลงไฟล์
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
    """บันทึกฐานข้อมูลผู้ใช้ลงไฟล์ JSON"""
    try:
        with open("users_db.json", "w", encoding="utf-8") as f:
            json.dump(st.session_state.USERS_DB, f, indent=4)
    except Exception as e:
        st.error(f"Error saving user database: {e}")

if "step" not in st.session_state:
    st.session_state.step = "login"
    st.session_state.phone = ""
    st.session_state.user = ""
    st.session_state.forgot_step = "input_phones"
    st.session_state.temp_otp = ""
    st.session_state.reset_phone = ""
    st.session_state.USERS_DB = load_user_db()


def logout():
    """เคลียร์ Session State และกลับไปหน้า Login"""
    keys_to_reset = ["step", "phone", "user", "forgot_step", "temp_otp", "reset_phone"]
    for key in keys_to_reset:
        if key in st.session_state:
            st.session_state[key] = ""
    st.session_state.step = "login"
    st.rerun()

# -----------------------------
# ส่วนแสดงผล (UI)
# -----------------------------

def display_login_page():
    """แสดงฟอร์มสำหรับล็อกอินด้วยรหัสผ่าน"""
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
                if phone in st.session_state.USERS_DB:
                    user_data = st.session_state.USERS_DB[phone]
                    if user_data["password"] is None:
                        st.session_state.phone = phone
                        st.session_state.step = "set_password"
                        st.rerun()
                    elif user_data["password"] == password:
                        st.session_state.user = user_data["name"]
                        st.session_state.phone = phone
                        st.session_state.step = "dashboard"
                        st.rerun()
                    else:
                        st.error("รหัสผ่านไม่ถูกต้อง")
                else:
                    st.error("ไม่พบเบอร์โทรศัพท์นี้ในระบบ")

        st.markdown("---")
        # เพิ่มปุ่มสำหรับฟังก์ชันลืมรหัสผ่าน
        if st.button("🔒 ลืมรหัสผ่าน", use_container_width=True):
            st.session_state.step = "forgot_password"
            st.session_state.forgot_step = "input_phones"
            st.rerun()
            
            
def display_password_page(mode="set"):
    """แสดงหน้าสำหรับตั้งค่าหรือเปลี่ยนรหัสผ่าน"""
    title_map = {
        "set": "ตั้งรหัสผ่านครั้งแรก",
        "change": "เปลี่ยนรหัสผ่าน",
    }
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
                user_data = st.session_state.USERS_DB[st.session_state.phone]
                
                if mode == "change" and user_data["password"] != current_password:
                    st.error("รหัสผ่านปัจจุบันไม่ถูกต้อง")
                elif not new_password:
                    st.error("รหัสผ่านใหม่ต้องไม่เป็นค่าว่าง")
                elif new_password != confirm_password:
                    st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน")
                else:
                    st.session_state.USERS_DB[st.session_state.phone]["password"] = new_password
                    save_user_db() # เรียกใช้ฟังก์ชันบันทึกข้อมูล
                    if mode == "change":
                        st.success("บันทึกรหัสผ่านใหม่เรียบร้อยแล้ว!")
                        st.session_state.step = "dashboard"
                        st.rerun()
                    else:
                        st.success("ตั้งรหัสผ่านใหม่สำเร็จ! กรุณาล็อกอินอีกครั้ง")
                        logout()
            
            if mode == "set":
                if st.button("⬅️ กลับไปหน้าล็อกอิน", use_container_width=True):
                    logout()
            else: # mode == "change"
                if st.button("⬅️ กลับไปหน้าแดชบอร์ด", use_container_width=True):
                    st.session_state.step = "dashboard"
                    st.rerun()

def display_forgot_password_page():
    """แสดงหน้าสำหรับลืมรหัสผ่านพร้อมการยืนยันจาก Admin"""
    st.title("🔒 ลืมรหัสผ่าน")
    st.markdown("กรุณาให้ผู้ดูแลระบบช่วยเหลือในการรีเซ็ตรหัสผ่าน")

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(border=True):
            st.markdown("#### <div style='text-align: center;'>รีเซ็ตรหัสผ่าน</div>", unsafe_allow_html=True)
            
            user_phone = st.text_input("เบอร์โทรศัพท์พนักงานที่ลืมรหัส", placeholder="กรอกเบอร์โทรศัพท์ 10 หลัก", max_chars=10, key="forgot_user_phone")
            admin_phone = st.text_input("เบอร์โทรศัพท์ผู้ดูแลระบบ", placeholder="กรอกเบอร์โทรศัพท์ผู้ดูแลระบบ", max_chars=10, type="password", key="forgot_admin_phone")
            new_password = st.text_input("รหัสผ่านใหม่", type="password", key="new_password")
            confirm_password = st.text_input("ยืนยันรหัสผ่านใหม่", type="password", key="confirm_new_password")

            if st.button("💾 บันทึกรหัสผ่านใหม่", use_container_width=True, type="primary"):
                if user_phone not in st.session_state.USERS_DB or st.session_state.USERS_DB[user_phone]["name"] == "ผู้ดูแลระบบ":
                    st.error("ไม่พบเบอร์โทรศัพท์พนักงานนี้ในระบบ")
                elif admin_phone != "0888888888":
                    st.error("เบอร์โทรศัพท์ผู้ดูแลระบบไม่ถูกต้อง")
                elif new_password != confirm_password or not new_password:
                    st.error("รหัสผ่านใหม่และการยืนยันไม่ตรงกัน หรือเป็นค่าว่าง")
                else:
                    st.session_state.USERS_DB[user_phone]["password"] = new_password
                    save_user_db() # เรียกใช้ฟังก์ชันบันทึกข้อมูล
                    st.success("ตั้งรหัสผ่านใหม่สำเร็จแล้ว! กรุณากลับไปหน้าล็อกอิน")
                    logout()

        if st.button("⬅️ กลับไปหน้าล็อกอิน", use_container_width=True):
            logout()


def display_dashboard():
    """แสดง Dashboard ของผู้ใช้"""
    # เนื้อหาใน st.sidebar จะถูกย้ายไปในเมนู 3 ขีดโดยอัตโนมัติบนมือถือ
    with st.sidebar:
        st.header("เมนู")
        st.info(f"ยินดีต้อนรับ,\n**{st.session_state.user}**")
        
        # ปุ่มเปลี่ยนรหัสผ่าน
        if st.button("🔑 เปลี่ยนรหัสผ่าน"):
            st.session_state.step = "change_password"
            st.rerun()
        
        # ปุ่มออกจากระบบ
        st.divider()
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)

    # เนื้อหาหลักของแดชบอร์ด
    st.header("📊 แดชบอร์ดสรุปข้อมูล")
    st.subheader(f"ของ **{st.session_state.user}**")

    df_full = load_data()

    if not df_full.empty and 'วันที่' in df_full.columns:
        df_full_cleaned = df_full.dropna(subset=['วันที่'])
        if not df_full_cleaned.empty:
            start_date = df_full_cleaned['วันที่'].min()
            end_date = df_full_cleaned['วันที่'].max()
            # ใช้ st.markdown และ CSS เพื่อควบคุมขนาดตัวอักษร
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
                    check_in_time = format_time(row.get('เข้างาน')) if 'เข้างาน' in row and pd.notna(row.get('เข้างาน')) else "N/A"
                    check_out_time = format_time(row.get('ออกงาน')) if 'ออกงาน' in row and pd.notna(row.get('ออกงาน')) else "N/A"
                    
                    time_display = f" {check_in_time}-{check_out_time}"

                    st.markdown(
                        f'<p style="font-size: 0.9rem; margin: 0;">- <b>{thai_date(row["วันที่"])}</b>{time_display} ({row["ข้อยกเว้น"]})</p>',
                        unsafe_allow_html=True
                    )
    
    st.divider()
    # ปุ่มออกจากระบบที่ด้านล่างของหน้าหลัก (สำหรับหน้าจอขนาดใหญ่)
    _ , btn_col, _ = st.columns([1, 0.5, 1])
    with btn_col:
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)

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
else: # dashboard
    display_dashboard()
