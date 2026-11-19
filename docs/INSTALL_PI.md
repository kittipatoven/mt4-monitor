# Raspberry Pi — ติดตั้งและใช้งาน

คู่มือนี้ใช้สคริปต์ `install.sh` ตัวเดียวติดตั้งทุกอย่าง: แพ็กเกจ, I2C, หาจอ LCD,
Python, API key, service ที่เปิดเองตอนบูต, คำสั่ง `mt4mon` และ Tailscale

## 1. ติดตั้ง (แบบเร็ว ~10 นาที)

### สิ่งที่ต้องมีก่อน
- Raspberry Pi ลง **Raspberry Pi OS** แล้ว (Bookworm/Trixie) ต่ออินเทอร์เน็ตได้ และเปิด SSH แล้ว
- ต่อจอ LCD ตาม [WIRING.md](WIRING.md) (อ่านเรื่องไฟ 5V ก่อนต่อ SDA/SCL)
- บัญชี Tailscale (ฟรี)

### ขั้นที่ 1 — สร้าง Tailscale auth key (ครั้งเดียว ใช้ได้ทั้ง Pi และ VPS)
เปิด https://login.tailscale.com/admin/settings/keys → **Generate auth key** → เปิด **Reusable** และ **Pre-approved** → Generate → คัดลอก key (`tskey-auth-...`)

### ขั้นที่ 2 — Pi: คำสั่งเดียว
บน Pi (ผ่าน SSH หรือคีย์บอร์ดของ Pi) วางบรรทัดนี้ เปลี่ยน `tskey-auth-XXXX` เป็น key ของคุณ:

```bash
curl -fsSL https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/pi/install.sh | sudo bash -s -- --ts-key tskey-auth-XXXX
```

ตัวติดตั้งดาวน์โหลดโปรเจกต์เอง ทำ 7 ขั้น (`[OK]` = ผ่าน) แล้วตอนจบจะพิมพ์ **คำสั่ง 1 บรรทัดสำหรับ VPS** ให้คัดลอก

| ขั้น | ทำอะไร |
|---|---|
| 1/7 Packages | ติดตั้ง i2c-tools และ Python libraries จาก apt (เร็วกว่า pip มาก) |
| 2/7 I2C | เปิด I2C และหาจอที่ `0x27` / `0x3F` ให้เอง |
| 3/7 App files | ติดตั้งโปรแกรมใน `/opt/mt4-monitor` |
| 4/7 Settings | สร้าง `/etc/mt4-monitor.env` พร้อม **API key แบบสุ่ม** |
| 5/7 Service | service เปิดเองตอนบูต + คำสั่ง `mt4mon` |
| 6/7 Tailscale | เข้าร่วม Tailscale ด้วย auth key (ไม่ต้องเปิดลิงก์) |
| 7/7 Summary | พิมพ์คำสั่งสำหรับ VPS |

> ถ้าบอกให้ `sudo reboot` (เฉพาะตอนเปิด I2C ครั้งแรก) ให้รีบูตแล้ววางบรรทัดเดิมอีกครั้ง

### ขั้นที่ 3 — VPS: คำสั่งเดียว + คลิก 3 ครั้ง
บน Windows VPS เปิด **PowerShell แบบ Run as administrator** แล้ววางบรรทัดที่ Pi พิมพ์ให้
(ดูซ้ำได้ด้วย `sudo mt4mon vps` บน Pi) หน้าตาประมาณนี้:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/vps/setup_vps.ps1))) -PiIp 100.x.y.z -ApiKey <key>"
```

สคริปต์จะ: ติดตั้ง Tailscale (ถามหา auth key) → ทดสอบว่าคุยกับ Pi และ key ถูก → หา MT4 เอง →
ใส่ `MonitorEA.mq4` (ตั้ง URL ของ Pi ให้แล้ว) + ไฟล์ key → compile

เหลือทำเองใน MT4 แค่ 3 อย่าง (สคริปต์คัดลอก URL ไว้ให้แล้ว แค่วาง):
1. Tools → Options → Expert Advisors → ติ๊ก Allow WebRequest → เพิ่ม `http://100.x.y.z` → OK
2. File → New Chart → สัญลักษณ์ใดก็ได้ (**ไม่ใช่กราฟที่ EA เทรดอยู่**)
3. Navigator → Expert Advisors → Refresh → ดับเบิลคลิก **MonitorEA** → แท็บ Common เอาติ๊ก Allow live trading ออก → OK

ภายใน 5 วินาที จอจะเปลี่ยนจาก `Waiting for MT4` เป็นข้อมูลจริง

ตัวเลือกเพิ่มของ VPS: `-TsKey tskey-auth-...` (ไม่ต้องถาม key), `-Magic 52025` (magic ของ EA ที่จะติดตาม)

### ติดตั้งแบบไม่ใช้อินเทอร์เน็ต / จากไฟล์ ZIP
คัดลอกโฟลเดอร์ `pi` ไปที่ Pi (`scp -r pi pi@<IP ของ Pi>:~/mt4-monitor`) แล้ว `cd ~/mt4-monitor && sudo bash install.sh --ts-key tskey-auth-XXXX`

## 2. ใช้งานประจำวัน — คำสั่ง `mt4mon`

| คำสั่ง | ใช้ทำอะไร |
|---|---|
| `mt4mon status` | service ทำงานไหม และข้อมูลจาก MT4 เข้าล่าสุดกี่วินาทีก่อน |
| `mt4mon logs` | ดู log สด (กด Ctrl+C เพื่อออก) |
| `mt4mon restart` / `stop` / `start` | สั่ง service |
| `mt4mon config` | แก้ค่าตั้ง (เปิด nano) แล้วรีสตาร์ตให้เอง |
| `mt4mon key` | แสดง API key |
| `mt4mon url` | แสดง URL ที่ต้องใส่ใน MT4 |
| `mt4mon vps` | แสดงคำสั่ง 1 บรรทัดสำหรับตั้งค่า VPS (มี key อยู่ในนั้น) |
| `mt4mon ip` | แสดง IP Tailscale และ IP ในบ้าน |
| `mt4mon i2c` | สแกน I2C (ควรเห็น `27` หรือ `3f`) |
| `mt4mon lcdtest` | เขียนข้อความทดสอบและไอคอนทั้งหมดลงจอ 8 วินาที |
| `mt4mon test` | ส่งข้อมูลปลอม 1 ครั้ง (จอจะโชว์ข้อมูลปลอมจนกว่า MT4 ส่งรอบถัดไป ~5 วินาที) |

ตัวอย่างผลของ `mt4mon status` เมื่อทุกอย่างปกติ:

```
● mt4-monitor.service - MT4 Trading Monitor V1 (LCD + API, read-only)
     Loaded: loaded (/etc/systemd/system/mt4-monitor.service; enabled; ...)
     Active: active (running) since ...

MT4 data : OK - last update 2.1s ago (154 since start)
```

## 3. อ่านหน้าจอ

ไอคอน ▲▼♥✓✗ และแถบ █▌· เป็นตัวอักษรพิเศษที่โหลดเข้า LCD (CGRAM) ตอนเริ่มทำงาน

**โหมดหน้าเดียว (ค่าเริ่มต้น `MT4MON_SINGLE_PAGE=1`):**

```
|▲+240.50  ORD 1♥|   P/L (▲ กำไร / ▼ ขาดทุน), จำนวนออเดอร์, ♥ กระพริบ = ข้อมูลยังเข้า
|EQ   10,240.50 ✓|   Equity, ✓ = เชื่อมโบรกเกอร์และ AutoTrading เปิดอยู่ (✗ = มีปัญหา)
```

มีปัญหาเมื่อไร หน้าแจ้งเตือนจะสลับกับหน้าหลักทุก 3 วินาที (รวม `!! AUTOTRADING IS OFF`)
ตั้ง `MT4MON_SINGLE_PAGE=0` เพื่อกลับไปใช้โหมดหลายหน้าตามตารางด้านล่าง

**โหมดหลายหน้า:**

| หน้า (เวลา) | บรรทัด 1 | บรรทัด 2 |
|---|---|---|
| หน้าหลัก (8 วิ) | `▲ +240.50    ♥2s` | `EQ     10,240.50` |
| บัญชี (3 วิ) | `BAL    10,000.00` | `FREE   10,214.32` |
| Margin (3 วิ) | `MARGIN     26.18` | `USE███▌··· 49.4%` |
| สถานะ (3 วิ) | `LINK ✓    2s USD` | `BROKER✓  AUTO✓` |
| CapyTrend (3 วิ) | `CAPY UNVERIFIED` | `ORD 1   ▲+240.50` |
| สรุปออเดอร์ (3 วิ) | `ORD 1 B0 S1 P0` | `LOT 0.07   ▲+241` |
| ออเดอร์ทีละตัว (3 วิ) | `XAUUSD SELL 0.07` | `90000001 ▲+241` |

- ♥ กระพริบทุกวินาทีเมื่อข้อมูลยังเข้ามา ตัวเลขข้างหลังคืออายุข้อมูล (วินาที)
- หน้าออเดอร์แสดงเฉพาะเมื่อมีออเดอร์ หน้า CapyTrend แสดงเฉพาะเมื่อตั้ง magic แล้ว

**การแจ้งเตือน (ไฟ backlight กระพริบ + หน้าแจ้งเตือนขึ้นก่อน):**
- ไม่มีข้อมูลเกิน 30 วินาที → `!! MT4 NO DATA` และค่าล่าสุดพร้อมป้าย `(OLD)`
- MT4 หลุดจากโบรกเกอร์ → `!! BROKER DISCONNECTED`
- ปุ่ม AutoTrading ปิด → `!! AUTOTRADING IS OFF`
- ขาดทุนลอยตัว ≥ 2% ของ Balance → `!! DRAWDOWN -2.4%  -850.40`

**ไฟจอ:** เปิดตลอดเวลา (ค่าเริ่มต้น) ถ้าต้องการปิดกลางคืน ตั้ง `MT4MON_NIGHT_START=23` และ `MT4MON_NIGHT_END=7`

## 4. ปรับค่าตั้ง

รัน `mt4mon config` แก้ค่าแล้วบันทึก (Ctrl+O, Enter, Ctrl+X) — service รีสตาร์ตให้เอง

| ค่า | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `MT4MON_SINGLE_PAGE` | `1` | `1` = หน้าเดียว, `0` = วนหลายหน้า |
| `MT4MON_DD_ALERT_PCT` | `2.0` | แจ้งเตือนเมื่อขาดทุนลอยตัวถึงกี่ % ของ Balance (`0` = ปิด) |
| `MT4MON_NIGHT_START` / `MT4MON_NIGHT_END` | `-1` / `7` | ปิดไฟจอช่วงกลางคืน เช่น `23` / `7` (`-1` = เปิดตลอด) |
| `MT4MON_STALE_SECONDS` | `30` | ไม่มีข้อมูลเกินกี่วินาทีถึงแจ้ง `MT4 NO DATA` |
| `MT4MON_HOME_SECONDS` / `MT4MON_PAGE_SECONDS` | `8` / `3` | เวลาแต่ละหน้า (โหมดหลายหน้า) |
| `MT4MON_LCD_ADDRESS` | หาให้อัตโนมัติ | address ของจอ |
| `MT4MON_PORT` | `80` | พอร์ต API — **อย่าเปลี่ยน** (MT4 ใช้ได้แค่ 80/443) |
| `MT4MON_API_KEY` | สุ่มตอนติดตั้ง | ถ้าเปลี่ยน ต้องแก้ `MonitorEA_key.txt` บน VPS ด้วย |

## 5. อัปเดตและถอนการติดตั้ง

**อัปเดตเป็นเวอร์ชันใหม่:** วางบรรทัด `curl ... | sudo bash` เดิมอีกครั้ง (ไม่ต้องใส่ `--ts-key` ถ้าล็อกอินแล้ว) —
API key และค่าตั้งเดิมจะถูกเก็บไว้ ค่าตั้งใหม่ ๆ จะถูกเพิ่มให้เอง

```bash
curl -fsSL https://raw.githubusercontent.com/kittipatoven/mt4-monitor/main/pi/install.sh | sudo bash
```

**ถอนการติดตั้ง:**

```bash
mt4mon uninstall           # ลบโปรแกรม เก็บ API key ไว้
mt4mon uninstall --purge   # ลบหมดรวม API key
```

(Tailscale และ I2C ยังอยู่ ถ้าจะลบ Tailscale ใช้ `sudo apt remove tailscale`)

## 6. แก้ปัญหา

| อาการ | ตรวจ / แก้ |
|---|---|
| ไฟจอติดแต่ไม่มีตัวอักษร หรือเป็นกล่องทึบ | หมุนสกรู contrast สีฟ้าหลังจอช้า ๆ |
| ไฟจอดับ | ถ้าตั้งโหมดกลางคืนไว้ ไฟดับช่วงนั้นเป็นปกติ / ถ้าไม่ใช่ ดู `mt4mon status` |
| `mt4mon i2c` ไม่เจอ `27`/`3f` | ตรวจสาย SDA↔Pin 3, SCL↔Pin 5, GND, VCC / รีบูตหลังเปิด I2C ครั้งแรก |
| จอค้าง `Waiting for MT4` | MonitorEA ยังไม่ส่ง — ดูแท็บ Experts ใน MT4 และ `mt4mon url` |
| แท็บ Experts: `err=5200` | URL ใช้พอร์ตอื่นที่ไม่ใช่ 80 — ใช้ URL จาก `mt4mon url` |
| แท็บ Experts: `err=4060` | ยังไม่ได้เพิ่ม URL ใน Allow WebRequest |
| แท็บ Experts: `HTTP 401` | key ไม่ตรง — เทียบ `mt4mon key` กับ `MonitorEA_key.txt` |
| จอขึ้น `!! MT4 NO DATA` | MT4/VPS ปิด, Tailscale หลุด (`mt4mon ip`), หรือ EA ถูกถอด |
| `mt4mon status` บอก API not answering | `mt4mon logs` ดูข้อผิดพลาด แล้ว `mt4mon restart` |

## ความปลอดภัย
- API ต้องใช้ `X-API-Key` ทุกครั้งที่ส่งหรืออ่านข้อมูลบัญชี (`/health` ไม่เปิดเผยยอดเงิน)
- ไฟล์ค่าตั้ง `/etc/mt4-monitor.env` อ่านได้เฉพาะ root, service รันด้วย user `mt4mon` ที่ไม่มีสิทธิ์ล็อกอิน
- แนะนำ: ใน Tailscale admin ตั้ง ACL ให้เฉพาะ VPS เข้าพอร์ต 80 ของ Pi ได้
- ระบบนี้อ่านข้อมูลอย่างเดียว ไม่สามารถเปิด/ปิด/แก้ออเดอร์ได้
