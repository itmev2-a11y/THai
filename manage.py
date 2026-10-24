"""จัดการฐานข้อมูลบัญชีผู้ใช้จากบรรทัดคำสั่ง  ตัวอย่าง:  python manage.py list"""
import argparse, getpass, re, sys, time, json
from werkzeug.security import generate_password_hash
from database import connect, init_db, DB_PATH

USER_RE = re.compile(r"^[A-Za-z0-9_.\u0E00-\u0E7F-]{3,30}$")
def when(t): return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"

def ask_password():
    p = getpass.getpass("รหัสผ่านใหม่ (อย่างน้อย 8 ตัว): ")
    if len(p) < 8:
        sys.exit("รหัสผ่านสั้นเกินไป")
    if p != getpass.getpass("ยืนยันรหัสผ่าน: "):
        sys.exit("รหัสผ่านไม่ตรงกัน")
    return p

def find(c, name):
    u = c.execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
    if not u:
        sys.exit(f"ไม่พบผู้ใช้ '{name}'")
    return u

def main():
    ap = argparse.ArgumentParser(description="จัดการฐานข้อมูลบัญชีผู้ใช้")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="สร้างตาราง (ถ้ายังไม่มี)")
    sub.add_parser("list", help="แสดงผู้ใช้ทั้งหมด")
    sub.add_parser("stats", help="สรุปจำนวนผู้ใช้และแต้ม")
    for n, h in [("show", "ดูรายละเอียดผู้ใช้"), ("create", "สร้างผู้ใช้"), ("reset-password", "ตั้งรหัสผ่านใหม่"), ("delete", "ลบผู้ใช้พร้อมข้อมูล")]:
        s = sub.add_parser(n, help=h); s.add_argument("username")
        if n == "delete": s.add_argument("--yes", action="store_true", help="ไม่ต้องถามยืนยัน")
    lg = sub.add_parser("log", help="ดูประวัติสมัคร/ล็อกอิน"); lg.add_argument("-n", type=int, default=20)
    a = ap.parse_args()

    init_db(); c = connect()
    if a.cmd == "init":
        print("พร้อมใช้งาน:", DB_PATH)
    elif a.cmd == "list":
        rows = c.execute("SELECT u.id,u.username,u.created,u.last_login,p.pts,p.don FROM users u LEFT JOIN progress p ON p.user_id=u.id ORDER BY u.id").fetchall()
        print(f"{'id':>3}  {'ชื่อผู้ใช้':<20} {'สมัครเมื่อ':<17} {'ล็อกอินล่าสุด':<17} {'แต้ม':>6} {'บริจาค':>6}")
        for r in rows:
            print(f"{r['id']:>3}  {r['username']:<20} {when(r['created']):<17} {when(r['last_login']):<17} {r['pts'] or 0:>6} {r['don'] or 0:>6}")
        print(f"รวม {len(rows)} บัญชี")
    elif a.cmd == "stats":
        r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(pts),0) p, COALESCE(SUM(don),0) d FROM users u LEFT JOIN progress p ON p.user_id=u.id").fetchone()
        print(f"ผู้ใช้ {r['n']} บัญชี | แต้มรวม {r['p']} | บริจาครวม {r['d']}")
    elif a.cmd == "show":
        u = find(c, a.username); p = c.execute("SELECT * FROM progress WHERE user_id=?", (u["id"],)).fetchone()
        print(f"id {u['id']} | {u['username']} | สมัคร {when(u['created'])} | ล็อกอินล่าสุด {when(u['last_login'])}")
        print(f"แต้ม {p['pts']} | บริจาค {p['don']} | คำที่ฝึกแล้ว: {', '.join(json.loads(p['done'])) or '-'}")
    elif a.cmd == "create":
        if not USER_RE.match(a.username): sys.exit("ชื่อผู้ใช้ต้องยาว 3-30 ตัว ใช้ตัวอักษร ตัวเลข _ . - เท่านั้น")
        pw = ask_password(); now = time.time()
        try:
            cur = c.execute("INSERT INTO users(username,pw_hash,created) VALUES(?,?,?)", (a.username, generate_password_hash(pw), now))
        except Exception:
            sys.exit("ชื่อผู้ใช้นี้ถูกใช้แล้ว")
        c.execute("INSERT INTO progress(user_id,updated) VALUES(?,?)", (cur.lastrowid, now)); c.commit()
        print("สร้างบัญชีแล้ว:", a.username)
    elif a.cmd == "reset-password":
        u = find(c, a.username)
        c.execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(ask_password()), u["id"])); c.commit()
        print("เปลี่ยนรหัสผ่านแล้ว:", u["username"])
    elif a.cmd == "delete":
        u = find(c, a.username)
        if not a.yes and input(f"พิมพ์ชื่อ '{u['username']}' เพื่อยืนยันการลบ: ") != u["username"]:
            sys.exit("ยกเลิก")
        c.execute("DELETE FROM users WHERE id=?", (u["id"],)); c.commit()
        print("ลบแล้ว:", u["username"])
    elif a.cmd == "log":
        for r in c.execute("SELECT * FROM login_log ORDER BY id DESC LIMIT ?", (a.n,)):
            print(f"{when(r['at'])}  {r['action']:<8} {'สำเร็จ' if r['ok'] else 'ล้มเหลว':<7} {r['username'] or '-':<20} {r['ip'] or '-'}")
    c.close()

if __name__ == "__main__":
    main()
