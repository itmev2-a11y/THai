-- ฐานข้อมูลบัญชีผู้ใช้ (SQLite) — ไฟล์นี้เป็นต้นแบบของตาราง ถูกใช้ตอนรัน app.py และ manage.py init
PRAGMA foreign_keys = ON;

-- บัญชีผู้ใช้: รหัสผ่านเก็บเป็นแฮช (ไม่เก็บรหัสผ่านจริง)
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT    NOT NULL UNIQUE COLLATE NOCASE,   -- ไม่แยกตัวพิมพ์เล็ก-ใหญ่
    pw_hash    TEXT    NOT NULL,
    created    REAL    NOT NULL,                         -- เวลา Unix
    last_login REAL
);

-- แต้มและความคืบหน้า แยกตามบัญชี (ลบผู้ใช้แล้วข้อมูลนี้ถูกลบตามอัตโนมัติ)
CREATE TABLE IF NOT EXISTS progress (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    pts     INTEGER NOT NULL DEFAULT 0 CHECK (pts >= 0),
    don     INTEGER NOT NULL DEFAULT 0 CHECK (don >= 0),
    done    TEXT    NOT NULL DEFAULT '{}',               -- JSON: คำที่ฝึกแล้ว
    cal     REAL    CHECK (cal IS NULL OR (cal >= 0 AND cal <= 1)),
    updated REAL
);

-- ประวัติการสมัคร/ล็อกอิน (เก็บล่าสุด 2,000 รายการ)
CREATE TABLE IF NOT EXISTS login_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username TEXT,
    action   TEXT    NOT NULL DEFAULT 'login',           -- login / register
    ok       INTEGER NOT NULL,                           -- 1 สำเร็จ, 0 ไม่สำเร็จ
    ip       TEXT,
    at       REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_log_user ON login_log (user_id, at);
