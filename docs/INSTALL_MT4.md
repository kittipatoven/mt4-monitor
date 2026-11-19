# ติดตั้ง MonitorEA บน MT4 (Windows VPS)

MonitorEA เป็น EA **ตัวใหม่แยกต่างหาก** ทำหน้าที่อ่านข้อมูลอย่างเดียว
ไม่มีคำสั่ง OrderSend / OrderModify / OrderClose และ **ไม่แก้ไขไฟล์ EA Capybara**

## 1. คัดลอกและ compile

1. MT4 → File → Open Data Folder → `MQL4\Experts\`
2. คัดลอก `MonitorEA.mq4` ไปไว้ที่นี่
3. เปิดด้วย MetaEditor (F4) → Compile (F7) → ต้องได้ `0 errors`
   (ถ้ามี error ให้ส่งข้อความ error มาทั้งหมด)

## 2. อนุญาต WebRequest

Tools → Options → Expert Advisors:
- ☑ Allow WebRequest for listed URL
- เพิ่ม `http://100.x.y.z` (พอร์ต 80 — MT4 WebRequest ใช้ได้แค่พอร์ต 80/443) (Tailscale IP ของ Pi, ไม่ต้องใส่ `/api/update`)

## 3. แนบ EA

1. เปิดกราฟ **ใหม่** (สัญลักษณ์ใดก็ได้ เช่น EURUSD M1) — อย่าใช้กราฟที่ Capybara ทำงานอยู่
   (MT4 ให้ EA ได้แค่ 1 ตัวต่อกราฟ ถ้าลากใส่กราฟ Capybara จะเป็นการ *แทนที่* Capybara)
2. ลาก MonitorEA ลงกราฟ ตั้งค่า:
   - `InpUrl` = `http://100.x.y.z/api/update`
   - `InpApiKey` = เว้นว่างไว้ แล้ววาง key ในไฟล์ `MQL4\Files\MonitorEA_key.txt` (บรรทัดเดียว, ค่าเดียวกับ `~/mt4-monitor/api_key.txt` บน Pi)
   - `InpCapybaraMagic` = magic number ของ Capybara ถ้าทราบ (ไม่ทราบให้ใช้ -1)
3. ไม่ต้องติ๊ก "Allow live trading" ก็ทำงานได้ เพราะ EA นี้ไม่เทรด

## 4. ตรวจสอบ

แท็บ Experts ควรเห็น `MonitorEA started. Sending to ...`
ถ้าเห็น `WebRequest failed, err=4060` → ยังไม่ได้เพิ่ม URL ในขั้นที่ 2
ถ้าเห็น `HTTP 401` → API key ไม่ตรงกัน

## เรื่องสถานะ Capybara

MT4 ไม่มี API มาตรฐานที่บอกได้อย่างน่าเชื่อถือว่า EA ตัวอื่นบนกราฟอื่นกำลังทำงานอยู่
จอจึงแสดง `CAPY:UNVERIFIED` เสมอ ส่วนที่ตรวจสอบได้จริงคือ:
- `LINK OK` — MonitorEA ส่งข้อมูลมาถึง Pi (MT4 เปิดอยู่)
- `BRK:Y` — MT4 เชื่อมต่อ broker
- `AUTO:Y` — ปุ่ม AutoTrading เปิดอยู่ (ทั้ง terminal ไม่ใช่เฉพาะ Capybara)
- `ORD n` — จำนวนออเดอร์ที่มี magic ตรงกับ Capybara (หลักฐานว่าเคยเปิดออเดอร์ ไม่ใช่หลักฐานว่ายังรันอยู่)
