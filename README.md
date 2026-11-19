# MT4 Trading Monitor V1 (read-only)

จอ LCD 16×2 บน Raspberry Pi แสดงกำไร/ขาดทุน, Equity และสถานะ MT4 จาก Windows VPS แบบสด — อ่านข้อมูลอย่างเดียว ไม่เปิด/ปิด/แก้ออเดอร์

```
MT4 (Windows VPS) --MonitorEA--> HTTP over Tailscale --> Raspberry Pi --I2C--> LCD 1602A
```

## ติดตั้งแบบเร็ว (~10 นาที)

1. **Tailscale auth key** — https://login.tailscale.com/admin/settings/keys → Generate auth key (เปิด Reusable + Pre-approved)
2. **Pi** — ต่อจอตาม [docs/WIRING.md](docs/WIRING.md) แล้ววางบน Pi:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/pi/install.sh | sudo bash -s -- --ts-key tskey-auth-XXXX
   ```
3. **VPS** — เปิด PowerShell แบบ Administrator แล้ววางบรรทัดที่ Pi พิมพ์ให้ตอนจบ (ดูซ้ำ: `sudo mt4mon vps`)
4. **MT4** — คลิก 3 ครั้งตามที่สคริปต์บอก: เพิ่ม URL ใน Allow WebRequest, เปิดกราฟใหม่, ลาก MonitorEA

รายละเอียดทั้งหมด: [docs/INSTALL_PI.md](docs/INSTALL_PI.md)

## ไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `pi/install.sh` | ตัวติดตั้งบน Pi (รันจาก GitHub หรือจากโฟลเดอร์ก็ได้, รันซ้ำ = อัปเดต) |
| `pi/mt4mon` | คำสั่งใช้งานประจำวัน (`mt4mon status`, `logs`, `config`, `vps` ...) |
| `pi/uninstall.sh` | ถอนการติดตั้ง |
| `pi/main.py`, `pi/lcd.py`, `pi/config.py` | API + หน้าจอ LCD |
| `vps/setup_vps.ps1` | ตั้งค่า VPS: Tailscale, MonitorEA, ไฟล์ key, compile |
| `mt4/MonitorEA.mq4` | EA อ่านข้อมูลบัญชี/ออเดอร์แล้วส่งไป Pi (ไม่เทรด) |
| `docs/WIRING.md` | การต่อวงจร + คำเตือน 5V |
| `docs/INSTALL_PI.md` | ติดตั้ง ใช้งาน ปรับค่า แก้ปัญหา |
| `docs/INSTALL_MT4.md` | ติดตั้ง MonitorEA ด้วยมือ |
| `docs/TEST_PLAN.md` | แผนทดสอบ |
