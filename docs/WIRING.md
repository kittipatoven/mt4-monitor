# การต่อวงจร LCD 1602A I2C (PCF8574) กับ Raspberry Pi 3 B+

| LCD backpack | Raspberry Pi 3 B+ |
|---|---|
| GND | Pin 6 (GND) |
| VCC | Pin 2 หรือ Pin 4 (5V) |
| SDA | Pin 3 (GPIO 2 / SDA1) |
| SCL | Pin 5 (GPIO 3 / SCL1) |

```
   Pi header (มองจากด้านบน, ช่อง SD card อยู่ซ้าย)
   Pin 1  3V3  [o o] 5V   Pin 2   <- VCC
   Pin 3  SDA  [o o] 5V   Pin 4
   Pin 5  SCL  [o o] GND  Pin 6   <- GND
```

## ⚠ ระวังไฟ 5V บนสาย SDA/SCL

GPIO ของ Pi รับได้แค่ **3.3V** โมดูล PCF8574 ส่วนใหญ่มีตัวต้านทาน pull-up (มัก 4.7kΩ หรือ 10kΩ)
ต่อไปที่ VCC ถ้าจ่าย 5V สาย SDA/SCL จะถูกดึงขึ้นไปเกิน 3.3V เล็กน้อย

ก่อนต่อ SDA/SCL ให้เลือกทางใดทางหนึ่ง:

1. **แนะนำ:** ใช้ Bidirectional Logic Level Shifter (เช่น BSS138 4 ช่อง)
   - ด้าน LV: 3.3V (Pin 1), GND, SDA, SCL ของ Pi
   - ด้าน HV: 5V (Pin 2), GND, SDA, SCL ของ LCD
2. **วัดก่อน:** จ่ายไฟ 5V+GND ให้โมดูลอย่างเดียว (ยังไม่ต่อ SDA/SCL)
   วัดแรงดันระหว่างขา SDA กับ GND ของโมดูล
   - ถ้าวัดได้ ~5V แปลว่ามี pull-up ไป 5V → ต้องใช้ level shifter หรือถอด pull-up บนโมดูล
   - ถ้าวัดได้ ~0V แปลว่าไม่มี pull-up บนโมดูล → ต่อตรงได้ (Pi มี pull-up 3.3V ในตัว)

## หลังต่อเสร็จ

- ไฟ backlight ควรติด
- ถ้าเห็นแต่สี่เหลี่ยมทึบแถวบน หรือไม่เห็นตัวอักษร ให้หมุน **potentiometer สีฟ้า** บนโมดูล (ปรับ contrast)
