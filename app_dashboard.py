import streamlit as st
import pandas as pd
import altair as alt
import datetime
import os

st.set_page_config(page_title="HR Dashboard", layout="wide")

# -----------------------------
# ฟังก์ชันวันที่แบบไทย
# -----------------------------
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
# โหลดไฟล์ Excel จาก repo เท่านั้น
# -----------------------------
def load_data(file_path):
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

df = load_data("attendances.xlsx")  # โหลดไฟล์จาก repo

# -----------------------------
# ปุ่ม Refresh
# -----------------------------
if st.button("🔄 Refresh ข้อมูล (Manual)"):
    st.experimental_rerun()

# -----------------------------
# นาฬิกา
# -----------------------------
now = datetime.datetime.now()
st.markdown(
    f"<div style='text-align:right; font-size:40px; color:#FF5733; font-weight:bold;'>"
    f"🗓 {thai_date(now)}  |  ⏰ {now.strftime('%H:%M:%S')}</div>",
    unsafe_allow_html=True
)

# -----------------------------
# ตรวจสอบว่ามีข้อมูล
# -----------------------------
if not df.empty:
    # ทำความสะอาดข้อมูล
    for col in ["ชื่อ-สกุล", "แผนก", "ข้อยกเว้น"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

    if "แผนก" in df.columns:
        df["แผนก"] = df["แผนก"].replace({"nan": "ไม่ระบุ", "": "ไม่ระบุ"})

    if "วันที่" in df.columns:
        df["วันที่"] = pd.to_datetime(df["วันที่"], errors='coerce')
        df["ปี"] = df["วันที่"].dt.year + 543
        df["เดือน"] = df["วันที่"].dt.to_period("M")

    df_filtered = df.copy()

    # --- Filter ปี
    years = ["-- แสดงทั้งหมด --"] + sorted(df["ปี"].dropna().unique(), reverse=True)
    selected_year = st.selectbox("📆 เลือกปี", years)
    if selected_year != "-- แสดงทั้งหมด --":
        df_filtered = df_filtered[df_filtered["ปี"] == int(selected_year)]

    # --- Filter เดือน
    if "เดือน" in df_filtered.columns and not df_filtered.empty:
        available_months = sorted(df_filtered["เดือน"].dropna().unique())
        month_options = ["-- แสดงทั้งหมด --"] + [format_thai_month(m) for m in available_months]
        selected_month = st.selectbox("📅 เลือกเดือน", month_options)
        if selected_month != "-- แสดงทั้งหมด --":
            mapping = {format_thai_month(m): str(m) for m in available_months}
            selected_period = mapping[selected_month]
            df_filtered = df_filtered[df_filtered["เดือน"].astype(str) == selected_period]

    # --- Filter แผนก
    departments = ["-- แสดงทั้งหมด --"] + sorted(df_filtered["แผนก"].dropna().unique())
    selected_dept = st.selectbox("🏢 เลือกแผนก", departments)
    if selected_dept != "-- แสดงทั้งหมด --":
        df_filtered = df_filtered[df_filtered["แผนก"] == selected_dept]

    # --- คำนวณประเภทการลา
    def leave_days(row):
        if "ครึ่งวัน" in str(row):
            return 0.5
        return 1

    df_filtered["ลาป่วย/ลากิจ"] = df_filtered["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"] else 0
    )
    df_filtered["ขาด"] = df_filtered["ข้อยกเว้น"].apply(
        lambda x: leave_days(x) if str(x) in ["ขาด", "ขาดครึ่งวัน"] else 0
    )
    df_filtered["สาย"] = df_filtered["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "สาย" else 0)
    df_filtered["พักผ่อน"] = df_filtered["ข้อยกเว้น"].apply(lambda x: 1 if str(x) == "พักผ่อน" else 0)

    leave_types = ["ลาป่วย/ลากิจ", "ขาด", "สาย", "พักผ่อน"]
    summary = df_filtered.groupby(["ชื่อ-สกุล", "แผนก"])[leave_types].sum().reset_index()

    st.title("📊 แดชบอร์ดการลา / ขาด / สาย")
    colors = {
        "ลาป่วย/ลากิจ": "#C70039",
        "ขาด": "#C70039",
        "สาย": "#C70039",
        "พักผ่อน": "#C70039",
    }

    # -----------------------------
    # เก็บชื่อพนักงานใน session
    # -----------------------------
    if "selected_employee" not in st.session_state:
        st.session_state.selected_employee = None

    tabs = st.tabs(leave_types)
    for t, leave in zip(tabs, leave_types):
        with t:
            st.subheader(f"🏆 จัดอันดับ {leave}")

            all_names = summary["ชื่อ-สกุล"].unique()
            default_name = st.session_state.selected_employee or "-- แสดงทั้งหมด --"

            selected_name_tab = st.selectbox(
                f"🔍 ค้นหาชื่อพนักงาน ({leave})",
                ["-- แสดงทั้งหมด --"] + list(all_names),
                index=(list(["-- แสดงทั้งหมด --"] + list(all_names)).index(default_name)
                       if default_name in list(all_names) else 0),
                key=f"search_{leave}"
            )

            if selected_name_tab != st.session_state.selected_employee:
                st.session_state.selected_employee = selected_name_tab

            if st.session_state.selected_employee != "-- แสดงทั้งหมด --":
                summary_filtered = summary[summary["ชื่อ-สกุล"] == st.session_state.selected_employee].reset_index(drop=True)
                person_data_full = df_filtered[df_filtered["ชื่อ-สกุล"] == st.session_state.selected_employee].reset_index(drop=True)
            else:
                summary_filtered = summary
                person_data_full = df_filtered

            st.markdown("### 📌 สรุปข้อมูลส่วนบุคคล")
            st.dataframe(summary_filtered, use_container_width=True)

            st.markdown("### 📅 วันที่ของการลา/ขาด/สาย/พักผ่อน")
            if not person_data_full.empty:
                if leave == "ลาป่วย/ลากิจ":
                    dates = person_data_full.loc[
                        person_data_full["ข้อยกเว้น"].isin(
                            ["ลาป่วย", "ลากิจ", "ลาป่วยครึ่งวัน", "ลากิจครึ่งวัน"]
                        ), ["วันที่", "ข้อยกเว้น"]
                    ]
                elif leave == "ขาด":
                    dates = person_data_full.loc[
                        person_data_full["ข้อยกเว้น"].isin(["ขาด", "ขาดครึ่งวัน"]), ["วันที่", "ข้อยกเว้น"]
                    ]
                else:
                    dates = person_data_full.loc[
                        person_data_full["ข้อยกเว้น"] == leave, ["วันที่", "ข้อยกเว้น"]
                    ]

                if not dates.empty:
                    total_days = dates["ข้อยกเว้น"].apply(leave_days).sum()
                    with st.expander(f"{leave} ({total_days} วัน)"):
                        date_list = []
                        for _, row in dates.iterrows():
                            label = row["วันที่"].strftime("%d/%m/%Y")
                            if "ครึ่งวัน" in str(row["ข้อยกเว้น"]):
                                label += f" ({row['ข้อยกเว้น']})"
                            date_list.append(label)
                        st.write(date_list)

            # ตารางอันดับ
            ranking = summary_filtered[["ชื่อ-สกุล", "แผนก", leave]].sort_values(by=leave, ascending=False).reset_index(drop=True)
            ranking.insert(0, "อันดับ", range(1, len(ranking)+1))

            st.markdown("### 🏅 ตารางอันดับ (ทุกคน)")
            st.dataframe(ranking, use_container_width=True)

            # กราฟ
            if not ranking.empty:
                chart = (
                    alt.Chart(ranking)
                    .mark_bar(cornerRadiusTopLeft=5, cornerRadiusBottomLeft=5, color=colors[leave])
                    .encode(
                        y=alt.Y("ชื่อ-สกุล:N", sort="-x", title="ชื่อ-สกุล"),
                        x=alt.X(leave + ":Q", title=leave),
                        tooltip=["อันดับ", "ชื่อ-สกุล", "แผนก", leave],
                    )
                    .properties(width=800, height=500)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("ไม่มีข้อมูลให้แสดง")
