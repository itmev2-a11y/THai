"""Thai sign language trainer: Flask backend (accounts, progress) + OpenCV/MediaPipe hand detection."""
import os, re, json, time, secrets, sqlite3, threading, urllib.request
import cv2, numpy as np
from flask import Flask, request, jsonify, session, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data.sqlite3")
KEY_PATH = os.path.join(BASE, ".secret_key")
MODEL_PATH = os.path.join(BASE, "models", "hand_landmarker.task")
COMPLEXITY = int(os.environ.get("HAND_COMPLEXITY", "1"))  # 1 = most accurate/stable, 0 = faster
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

if not os.path.exists(KEY_PATH):
    with open(KEY_PATH, "w") as f:
        f.write(secrets.token_hex(32))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="")
app.secret_key = open(KEY_PATH).read().strip()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  MAX_CONTENT_LENGTH=1024 * 1024, PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30)

# ---------- database ----------
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()

def init_db():
    c = sqlite3.connect(DB_PATH)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL,
        pw_hash TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS progress(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        pts INTEGER NOT NULL DEFAULT 0, don INTEGER NOT NULL DEFAULT 0, done TEXT NOT NULL DEFAULT '{}', cal REAL);
    """)
    c.commit(); c.close()

def get_progress(uid):
    r = db().execute("SELECT pts,don,done,cal FROM progress WHERE user_id=?", (uid,)).fetchone()
    if not r:
        return {"pts": 0, "don": 0, "done": {}, "cal": None}
    return {"pts": r["pts"], "don": r["don"], "done": json.loads(r["done"]), "cal": r["cal"]}

# ---------- auth ----------
USER_RE = re.compile(r"^[A-Za-z0-9_.\u0E00-\u0E7F-]{3,30}$")
FAILS = {}  # (ip, username) -> [count, first_time]

def locked(key):
    f = FAILS.get(key)
    if not f:
        return False
    if time.time() - f[1] > 60:
        FAILS.pop(key, None)
        return False
    return f[0] >= 5

def fail(key):
    f = FAILS.setdefault(key, [0, time.time()])
    f[0] += 1

def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return db().execute("SELECT id,username FROM users WHERE id=?", (uid,)).fetchone()

def payload(u):
    return {"user": u["username"], "progress": get_progress(u["id"]), "detector": detector.available()}

def creds():
    j = request.get_json(silent=True) or {}
    return str(j.get("username", "")).strip(), str(j.get("password", ""))

@app.post("/api/register")
def register():
    name, pw = creds()
    if not USER_RE.match(name):
        return jsonify(error="ชื่อผู้ใช้ต้องยาว 3-30 ตัว ใช้ตัวอักษร ตัวเลข _ . - เท่านั้น"), 400
    if len(pw) < 8 or len(pw) > 100:
        return jsonify(error="รหัสผ่านต้องยาว 8-100 ตัวอักษร"), 400
    try:
        cur = db().execute("INSERT INTO users(username,pw_hash,created) VALUES(?,?,?)",
                           (name, generate_password_hash(pw), time.time()))
        db().execute("INSERT INTO progress(user_id) VALUES(?)", (cur.lastrowid,))
        db().commit()
    except sqlite3.IntegrityError:
        return jsonify(error="ชื่อผู้ใช้นี้ถูกใช้แล้ว"), 409
    session.clear(); session.permanent = True; session["uid"] = cur.lastrowid
    return jsonify(payload(current_user()))

@app.post("/api/login")
def login():
    name, pw = creds()
    key = (request.remote_addr, name.lower())
    if locked(key):
        return jsonify(error="ลองผิดหลายครั้งเกินไป กรุณารอ 1 นาที"), 429
    u = db().execute("SELECT id,username,pw_hash FROM users WHERE username=?", (name,)).fetchone()
    if not u or not check_password_hash(u["pw_hash"], pw):
        fail(key)
        return jsonify(error="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"), 401
    FAILS.pop(key, None)
    session.clear(); session.permanent = True; session["uid"] = u["id"]
    return jsonify(payload(u))

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    u = current_user()
    if not u:
        return jsonify(user=None, detector=detector.available())
    return jsonify(payload(u))

@app.post("/api/progress")
def save_progress():
    u = current_user()
    if not u:
        return jsonify(error="กรุณาเข้าสู่ระบบ"), 401
    j = request.get_json(silent=True) or {}
    try:
        pts, don = int(j.get("pts", 0)), int(j.get("don", 0))
        done = j.get("done", {})
        cal = j.get("cal")
        cal = None if cal is None else float(cal)
    except (TypeError, ValueError):
        return jsonify(error="ข้อมูลไม่ถูกต้อง"), 400
    if not (0 <= pts <= 10_000_000 and 0 <= don <= 10_000_000) or not isinstance(done, dict) or len(done) > 200:
        return jsonify(error="ข้อมูลไม่ถูกต้อง"), 400
    if cal is not None and not (0.0 <= cal <= 1.0):
        return jsonify(error="ข้อมูลไม่ถูกต้อง"), 400
    done = {str(k)[:40]: 1 for k in done}
    db().execute("UPDATE progress SET pts=?,don=?,done=?,cal=? WHERE user_id=?",
                 (pts, don, json.dumps(done), cal, u["id"]))
    db().commit()
    return jsonify(ok=True)

# ---------- hand detection (OpenCV preprocessing + MediaPipe) ----------
CLAHE = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

def preprocess(img):
    """Resize, even out lighting with CLAHE on the L channel, return RGB."""
    h, w = img.shape[:2]
    if w > 320:
        img = cv2.resize(img, (320, int(h * 320 / w)), interpolation=cv2.INTER_AREA)
    mean, std = cv2.meanStdDev(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    if mean[0][0] < 100 or std[0][0] < 35:  # only fix dark / flat images; skip to save time
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        img = cv2.cvtColor(cv2.merge((CLAHE.apply(l), a, b)), cv2.COLOR_LAB2BGR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

class Detector:
    def __init__(self):
        self.lock = threading.Lock()
        self.h = None; self.kind = None; self.error = None; self.ts = 0; self.tried = False

    def _init(self):
        self.tried = True
        try:
            import mediapipe as mp
            self.mp = mp
            if hasattr(mp, "solutions"):
                self.h = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2, model_complexity=COMPLEXITY,
                                                  min_detection_confidence=0.6, min_tracking_confidence=0.5)
                self.kind = "solutions"
            else:  # newer MediaPipe: Tasks API needs the .task model file
                from mediapipe.tasks import python as mpt
                from mediapipe.tasks.python import vision
                if not os.path.exists(MODEL_PATH):
                    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
                    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
                opts = vision.HandLandmarkerOptions(
                    base_options=mpt.BaseOptions(model_asset_path=MODEL_PATH),
                    running_mode=vision.RunningMode.VIDEO, num_hands=2,
                    min_hand_detection_confidence=0.6, min_tracking_confidence=0.5)
                self.h = vision.HandLandmarker.create_from_options(opts)
                self.kind = "tasks"
        except Exception as e:  # noqa
            self.error = str(e); self.h = None

    def available(self):
        with self.lock:
            if not self.tried:
                self._init()
            return self.h is not None

    def detect(self, rgb):
        with self.lock:
            if not self.tried:
                self._init()
            if self.h is None:
                return None
            if self.kind == "solutions":
                res = self.h.process(rgb)
                hands = res.multi_hand_landmarks or []
                sc = res.multi_handedness or []
                out = []
                for i, hd in enumerate(hands):
                    score = sc[i].classification[0].score if i < len(sc) else 1.0
                    if score >= 0.6:  # drop low-confidence detections
                        out.append([[round(p.x, 4), round(p.y, 4)] for p in hd.landmark])
                return out
            self.ts += 33
            img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self.h.detect_for_video(img, self.ts)
            out = []
            for i, hd in enumerate(res.hand_landmarks):
                score = res.handedness[i][0].score if i < len(res.handedness) and res.handedness[i] else 1.0
                if score >= 0.6:
                    out.append([[round(p.x, 4), round(p.y, 4)] for p in hd])
            return out

detector = Detector()

@app.post("/api/detect")
def detect():
    if not current_user():
        return jsonify(error="กรุณาเข้าสู่ระบบ"), 401
    arr = np.frombuffer(request.get_data(), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR) if arr.size else None
    if img is None:
        return jsonify(error="รูปภาพไม่ถูกต้อง"), 400
    t0 = time.perf_counter()
    hands = detector.detect(preprocess(img))
    if hands is None:
        return jsonify(error="detector_unavailable"), 503
    return jsonify(hands=hands, ms=int((time.perf_counter() - t0) * 1000))

@app.get("/")
def index():
    return app.send_static_file("index.html")

if __name__ == "__main__":
    init_db()
    from werkzeug.serving import WSGIRequestHandler
    WSGIRequestHandler.protocol_version = "HTTP/1.1"  # keep-alive: no new connection per frame
    print("เปิดเบราว์เซอร์ที่ http://127.0.0.1:5000  (ใช้ 127.0.0.1 ไม่ใช่ localhost เพื่อลดความหน่วงบน Windows)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
