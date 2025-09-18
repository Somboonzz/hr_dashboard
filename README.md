# HR Dashboard

โปรเจกต์นี้เป็น **HR Dashboard** ที่พัฒนาด้วย [Streamlit](https://streamlit.io)  
สำหรับแสดงผลข้อมูลการขาด ลา มาสาย ของพนักงาน โดยใช้ข้อมูลจากไฟล์ `attendances.xlsx`

## การติดตั้งและใช้งาน

1. สร้าง virtual environment (ถ้ายังไม่มี)
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # สำหรับ Linux/Mac
   .venv\Scripts\activate      # สำหรับ Windows
   ```

2. ติดตั้ง dependency
   ```bash
   pip install -r requirements.txt
   ```

3. รันแอป Streamlit
   ```bash
   streamlit run app_dashboard.py
   ```

4. เปิดเว็บเบราว์เซอร์ไปที่
   ```
   http://localhost:8501
   ```

## โครงสร้างโปรเจกต์

```
.
├── app_dashboard.py      # ไฟล์หลักของแอป
├── attendances.xlsx      # ข้อมูลดิบการเข้า-ออกงาน
├── requirements.txt      # รายการ dependency
├── README.md             # คำอธิบายโปรเจกต์
└── .venv/                # virtual environment
```
