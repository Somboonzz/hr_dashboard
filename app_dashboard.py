import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os
import pytz
import random

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
    return dt.strftime(f"%d/%m/{dt.year + 543}")

# -----------------------------
# การจัดการข้อมูล
# -----------------------------
@st.cache_data # Cache ข้อมูลเพื่อประสิทธิภาพที่ดีขึ้น
def load_data(file_path="attendances.xlsx"):
    """โหลดข้อมูลจากไฟล์ Excel และคืนค่าเป็น DataFrame"""
    if file_path and os.path.exists(file_path):
        return pd.read_excel(file_path, engine='openpyxl')
    else:
        st.warning("❌ ไม่พบไฟล์ Excel: attendances.xlsx")
        return pd.DataFrame()

def process_user_data(df, user_name):
    """ประมวลผลข้อมูลสำหรับผู้ใช้ที่ระบุ"""
    df_user = df[df["ชื่อ-สกุล"] == user_name].copy()
    if df_user.empty:
        return pd.DataFrame(), pd.DataFrame()

    # --- ทำความสะอาดข้อมูล ---
    for col in ["ชื่อ-สกุล", "แผนก", "ข้อยกเว้น"]:
        if col in df_user.columns:
            df_user[col] = df_user[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    if "แผนก" in df_user.columns:
        df_user["แผนก"] = df_user["แผนก"].replace({"nan": "ไม่ระบุ", "": "ไม่ระบุ"})
    if "วันที่" in df_user.columns:
        df_user["วันที่"] = pd.to_datetime(df_user["วันที่"], errors='coerce')

    # --- คำนวณประเภทการลา ---
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
if "step" not in st.session_state:
    st.session_state.step = "login"
    st.session_state.phone = ""
    st.session_state.otp_input = ""
    st.session_state.otp_sent = False
    st.session_state.user = ""
    st.session_state.generated_otp = ""

# ผู้ใช้ตัวอย่าง (ในระบบจริงควรดึงจากฐานข้อมูล)
USERS_DB = {
    "0989620358": "นายสมบูรณ์ เหนือกอง",
    "0951646928": "นางสาวพรทิพย์ สุขอนันต์",
    "0618741894": "นายอมร เพ็งโสภา",
}

def logout():
    """เคลียร์ Session State และกลับไปหน้า Login"""
    st.session_state.step = "login"
    st.session_state.phone = ""
    st.session_state.otp_input = ""
    st.session_state.otp_sent = False
    st.session_state.user = ""
    st.session_state.generated_otp = ""
    st.rerun()

# -----------------------------
# ส่วนแสดงผล (UI)
# -----------------------------

def display_login_page():
    """แสดงฟอร์มสำหรับล็อกอิน"""
    st.title("📊 HR Dashboard")
    st.markdown("กรุณาเข้าสู่ระบบเพื่อดูข้อมูลการเข้า-ออกงานของคุณ")

    col1, col2, col3 = st.columns([1, 1.5, 1]) # จัดคอลัมน์ให้อยู่ตรงกลาง

    with col2:
        with st.container(border=True):
            st.markdown("#### <div style='text-align: center;'>เข้าสู่ระบบด้วย OTP</div>", unsafe_allow_html=True)
            
            phone_input = st.text_input(
                "เบอร์โทรศัพท์",
                key="phone",
                placeholder="กรอกเบอร์โทรศัพท์ 10 หลัก",
                max_chars=10
            )

            if st.button("📲 ขอรหัส OTP", use_container_width=True, type="primary"):
                if phone_input in USERS_DB:
                    st.session_state.otp_sent = True
                    st.session_state.generated_otp = str(random.randint(1000, 9999))
                    # ในระบบจริง จะส่ง OTP ผ่าน SMS ที่นี่
                    st.success(f"OTP ถูกส่งไปที่เบอร์ {phone_input} แล้ว")
                    st.info(f"สำหรับทดสอบ: รหัส OTP ของคุณคือ **{st.session_state.generated_otp}**")
                else:
                    st.error("ไม่พบเบอร์โทรศัพท์นี้ในระบบ")

            if st.session_state.otp_sent:
                otp_input = st.text_input(
                    "รหัส OTP",
                    key="otp_input",
                    placeholder="กรอกรหัส 4 หลักที่ได้รับ",
                    max_chars=4
                )
                if st.button("✅ ยืนยัน OTP", use_container_width=True):
                    if otp_input == st.session_state.generated_otp:
                        st.session_state.user = USERS_DB[st.session_state.phone]
                        st.session_state.step = "dashboard"
                        st.rerun() # สั่งให้แอปฯ โหลดใหม่เพื่อไปหน้า dashboard
                    else:
                        st.error("รหัส OTP ไม่ถูกต้อง")

def display_dashboard():
    """แสดง Dashboard ของผู้ใช้"""
    
    # --- Sidebar ---
    with st.sidebar:
        st.header("เมนู")
        st.info("แดชบอร์ดนี้แสดงข้อมูลการเข้า-ออกงานส่วนบุคคล")

    # --- Main Content ---
    # --- ส่วนหัว (Header) แบบปกติ ---
    st.title(f"📊 แดชบอร์ดสรุปข้อมูล")
    st.caption(f"ข้อมูลของคุณ: **{st.session_state.user}**")
    st.divider()

    df_full = load_data()
    df_user, summary = process_user_data(df_full, st.session_state.user)

    if summary.empty:
        st.info("ไม่พบข้อมูลการเข้า-ออกงานของคุณ")
        # --- ส่วนท้าย (Footer) สำหรับปุ่มออกจากระบบ ---
        # แม้ไม่พบข้อมูล ก็ยังต้องมีปุ่มออกจากระบบ
        st.divider()
        _ , btn_col, _ = st.columns([1, 0.5, 1])
        with btn_col:
            st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)
        return

    # --- แสดงการ์ดข้อมูลสรุป (Metrics) ---
    st.markdown("### 🗓️ สรุปภาพรวม")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ลาป่วย/ลากิจ (วัน)", summary["ลาป่วย/ลากิจ"].sum())
    col2.metric("ขาดงาน (วัน)", summary["ขาด"].sum())
    col3.metric("มาสาย (ครั้ง)", int(summary["สาย"].sum()))
    col4.metric("วันพักผ่อน (วัน)", int(summary["พักผ่อน"].sum()))
    st.divider()

    # --- แสดงรายละเอียดและกราฟ ---
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
    ).properties(
        title='กราฟเปรียบเทียบข้อมูล'
    )
    st.altair_chart(chart, use_container_width=True)

    # --- แสดงรายการวันที่แบบ Expander ---
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
                for _, row in dates_df.iterrows():
                    st.markdown(f"- **{thai_date(row['วันที่'])}**: {row['ข้อยกเว้น']}")
    
    # --- ส่วนท้าย (Footer) สำหรับปุ่มออกจากระบบ ---
    st.divider()
    _ , btn_col, _ = st.columns([1, 0.5, 1]) # สร้าง 3 คอลัมน์เพื่อให้ปุ่มอยู่ตรงกลาง
    with btn_col:
        st.button("🚪 ออกจากระบบ", on_click=logout, use_container_width=True)


# -----------------------------
# Main App Logic
# -----------------------------
if st.session_state.step == "login":
    display_login_page()
else:
    display_dashboard()