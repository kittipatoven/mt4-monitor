# แผนทดสอบ V1

ติ๊กทีละข้อ บันทึกผล (ผ่าน / ไม่ผ่าน + หมายเหตุ)

## A. Hardware
- [ ] A1 `sudo i2cdetect -y 1` เจอ 0x27 หรือ 0x3F
- [ ] A2 `lcd.py --address 0x..` แสดง `MT4 MONITOR V1` / `LCD TEST OK`
- [ ] A3 ปรับ contrast แล้วอ่านง่ายทั้ง 2 บรรทัด
- [ ] A4 ถอดสาย SDA ระหว่างทำงาน → service ไม่ crash (`journalctl` มี `LCD error ... retrying`), เสียบกลับแล้วจอกลับมาเอง

## B. API บน Pi
- [ ] B1 `systemctl status mt4-monitor` = active (running)
- [ ] B2 ก่อนส่งข้อมูล จอแสดง `Waiting for MT4`
- [ ] B3 `test_sender.py` ด้วย key ถูก → `200 {"ok":true}` และจอวนครบทุกหน้า
- [ ] B4 `test_sender.py` ด้วย key ผิด → `401`
- [ ] B5 หยุดส่งเกิน 30 วินาที → จอแสดง `!! MT4 NO DATA` และค่าที่ติดป้าย `(OLD)`
- [ ] B6 reboot Pi → service เริ่มเองและจอกลับมาทำงาน

## C. เครือข่าย
- [ ] C1 จาก VPS: `Invoke-RestMethod http://100.x.y.z/health` ได้ผล
- [ ] C2 `test_sender.py --url http://100.x.y.z` จาก VPS ได้ 200

## D. MT4
- [ ] D1 MonitorEA compile ได้ 0 errors (warnings ให้บันทึกไว้)
- [ ] D2 แท็บ Experts ไม่มี err 4060 / HTTP 401
- [ ] D3 Balance, Equity, Margin, Free Margin บนจอตรงกับแท็บ Trade ของ MT4 (คลาดเคลื่อนได้ตามรอบส่ง 5 วินาที)
- [ ] D4 จำนวนออเดอร์และ P/L ต่อออเดอร์ตรงกับ MT4 (P/L รวม swap + commission)
- [ ] D5 ปิด MT4 → ภายใน 30 วินาทีจอแสดง `!! MT4 NO DATA`
- [ ] D6 ตัดเน็ต VPS กับ broker (หรือ login ผิด) → จอแสดง `!! BROKER DISCONNECTED`
- [ ] D7 ยืนยันว่า Capybara ยังทำงานบนกราฟเดิม ไฟล์ Capybara ไม่ถูกแก้ และ MonitorEA ไม่เปิด/ปิดออเดอร์ใด ๆ
- [ ] D8 ปิดปุ่ม AutoTrading ชั่วคราว (ในช่วงที่ไม่มีความเสี่ยง) → จอแสดง `AUTO:N`
