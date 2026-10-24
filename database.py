"""ศูนย์กลางการเชื่อมต่อฐานข้อมูล SQLite (ใช้ร่วมกันระหว่าง app.py และ manage.py)"""
import os, sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SIGN_DB", os.path.join(BASE, "data.sqlite3"))
SCHEMA_PATH = os.path.join(BASE, "schema.sql")

def connect():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")  # ต้องเปิดทุกการเชื่อมต่อ ไม่งั้น ON DELETE ไม่ทำงาน
    return c

def _cols(c, table):
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}

def init_db():
    """สร้างตารางถ้ายังไม่มี และเพิ่มคอลัมน์ใหม่ให้ฐานข้อมูลรุ่นเก่า (ปลอดภัยที่จะเรียกซ้ำ)"""
    c = connect()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        c.executescript(f.read())
    if "last_login" not in _cols(c, "users"):
        c.execute("ALTER TABLE users ADD COLUMN last_login REAL")
    if "updated" not in _cols(c, "progress"):
        c.execute("ALTER TABLE progress ADD COLUMN updated REAL")
    c.commit()
    c.close()
