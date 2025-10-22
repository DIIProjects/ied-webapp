# core.py
import os
import re
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
import streamlit as st
from werkzeug.security import generate_password_hash

# ------------------- secrets/env helpers (no import from auth to avoid cycles) -------------------
def read_secret(key: str, default=None):
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
    return os.getenv(key, default)

# ------------------- CONFIG -------------------
DB_URL = read_secret("DB_URL", "sqlite:///ieday.db")
ATTENDANCE_CSV = read_secret("ATTENDANCE_CSV", "presenze.csv")
CV_DIR = read_secret("CV_DIR", "cv")

engine = create_engine(DB_URL, future=True)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS event_company (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  UNIQUE(event_id, company_id)
);
CREATE TABLE IF NOT EXISTS checkin (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  student TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS booking (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  student TEXT NOT NULL,
  slot TEXT NOT NULL,
  cv_path TEXT,
  cv_uploaded_at TEXT,
  matricola TEXT,
  UNIQUE(event_id, company_id, slot)
);
CREATE TABLE IF NOT EXISTS roundtable (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    room TEXT,
    info TEXT,
    UNIQUE(event_id, name)
);
CREATE TABLE IF NOT EXISTS roundtable_booking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    roundtable_id INTEGER NOT NULL,
    student TEXT NOT NULL,
    created_at TEXT,
    attended INTEGER DEFAULT 0,
    matricola TEXT,
    UNIQUE(event_id, roundtable_id, student)
);
CREATE TABLE IF NOT EXISTS interview_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  booking_id INTEGER NOT NULL UNIQUE,
  start_time TEXT,
  end_time TEXT,
  status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS notification (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  student TEXT NOT NULL,
  slot_from TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  read_at TEXT
);
CREATE TABLE IF NOT EXISTS student (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    givenName TEXT NOT NULL,
    sn TEXT NOT NULL,
    matricola TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    plenary_attendance INTEGER
);
CREATE TABLE IF NOT EXISTS student_matricola (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student TEXT UNIQUE NOT NULL,
        matricola TEXT NOT NULL
);
'''

SEED = [
    ("INSERT OR IGNORE INTO event (id, name, is_active) VALUES (1, 'Industrial Engineering Day', 1)", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('BLM Group')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Biko Meccanica')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Capi Group')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Colorobbia (Industrie Bitossi)')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Coster')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Dalmec')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Danieli')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Donatoni')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Global Wafers (Memc)')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('IIT hydrogen')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Iveco')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Infeon Technologies Italia')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Kosme')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('La Sportiva')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Leitner')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Lincotek')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Mahle')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Optoi')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Pittini Group')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Polytec (BM Group)')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Roechling')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Scania')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Tassullo')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Tenaris')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Turin Tech')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Vimar')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Zobele')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Watts Industries Italia')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Wuerth')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('ZF')", {}),
    ("INSERT OR IGNORE INTO event_company (event_id, company_id) SELECT 1, c.id FROM company c", {}),
]

# ------------------- DB bootstrap -------------------
def init_db():
    with engine.begin() as conn:
        for stmt in SCHEMA.split(';'):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        for q, p in SEED:
            conn.execute(text(q), p)

def migrate_db():
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE booking ADD COLUMN cv_path TEXT"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE booking ADD COLUMN cv_uploaded_at TEXT"))
        except Exception:
            pass

def ensure_dirs():
    os.makedirs(CV_DIR, exist_ok=True)

# ------------------- Queries & helpers -------------------
def get_active_event(conn):
    return conn.execute(
        text("SELECT id, name FROM event WHERE is_active=1 LIMIT 1")
    ).mappings().first()

def get_companies(conn, event_id):
    q = text("""
        SELECT c.id, c.name
        FROM company c
        JOIN event_company ec ON ec.company_id = c.id
        WHERE ec.event_id = :e
        ORDER BY c.name
    """)
    return list(conn.execute(q, {"e": event_id}).mappings())

def get_roundtables(conn, event_id):
    q = text("""
        SELECT 
            r.id,
            r.name,
            r.room,
            r.info,
            COUNT(rb.id) AS booked
        FROM roundtable r
        LEFT JOIN roundtable_booking rb 
            ON rb.roundtable_id = r.id
        WHERE r.event_id = :e
        GROUP BY r.id, r.name, r.room, r.info
        ORDER BY r.id
    """)
    return list(conn.execute(q, {"e": event_id}).mappings())

def book_roundtable(conn, event_id, roundtable_id, student, matricola=None):
    conn.execute(
        text("""
            INSERT INTO roundtable_booking (event_id, roundtable_id, student, created_at, matricola)
            VALUES (:event_id, :roundtable_id, :student, datetime('now'), :matricola)
            ON CONFLICT(event_id, roundtable_id, student) DO NOTHING
        """),
        {
            "event_id": event_id,
            "roundtable_id": roundtable_id,
            "student": student,
            "matricola": matricola
        }
    )


def get_student_roundtable_bookings(conn, event_id: int, student: str):
    """
    Returns a list of roundtable bookings for a given student and event.
    Each booking is a dict with at least roundtable_id.
    """
    q = text("""
        SELECT roundtable_id
        FROM roundtable_booking
        WHERE event_id = :e AND student = :s
    """)
    return list(conn.execute(q, {"e": event_id, "s": student}).mappings())

# Check-in
def is_checked_in(conn, event_id, student):
    return conn.execute(
        text("SELECT 1 FROM checkin WHERE event_id=:e AND student=:s LIMIT 1"),
        {"e": event_id, "s": student}
    ).first() is not None

def toggle_checkin(conn, event_id, student):
    if is_checked_in(conn, event_id, student):
        conn.execute(
            text("DELETE FROM checkin WHERE event_id=:e AND student=:s"),
            {"e": event_id, "s": student}
        )
        return False
    else:
        conn.execute(
            text("INSERT INTO checkin (event_id, student, created_at) VALUES (:e,:s,:t)"),
            {"e": event_id, "s": student, "t": datetime.utcnow().isoformat()}
        )
        return True

# Booking
def generate_slots(step=15):
    """
    Genera slot di colloqui a scaglioni di 15 minuti
    negli intervalli:
      - 11:30 → 13:00
      - 14:30 → 16:30
    """
    slots = []
    ranges = [("11:30", "13:00"), ("14:30", "16:30")]

    for start, end in ranges:
        start_dt = datetime.strptime(start, "%H:%M")
        end_dt = datetime.strptime(end, "%H:%M")
        while start_dt < end_dt:
            slots.append(start_dt.strftime("%H:%M"))
            start_dt += timedelta(minutes=step)

    return slots

def get_bookings(conn, event_id, company_id):
    q = text("SELECT id, slot, student, cv_path FROM booking WHERE event_id=:e AND company_id=:c")
    return list(conn.execute(q, {"e": event_id, "c": company_id}).mappings())

def get_booking_by_id(conn, booking_id):
    q = text("SELECT id, event_id, company_id, student, slot, cv_path FROM booking WHERE id=:id")
    return conn.execute(q, {"id": booking_id}).mappings().first()

def sanitize_filename(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "_", s)
    return s[:120]

def build_cv_filename(event_id: int, company_id: int, student: str, slot: str, orig_name: str | None) -> str:
    base = f"e{event_id}_c{company_id}_{sanitize_filename(student)}_{slot.replace(':','')}"
    ext = ".pdf"
    if orig_name and orig_name.lower().endswith(".pdf"):
        ext = ".pdf"
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    return os.path.join(CV_DIR, f"{base}_{ts}{ext}")

def save_cv_file(file_uploader, event_id: int, company_id: int, student: str, slot: str) -> str | None:
    if not file_uploader:
        return None
    ensure_dirs()
    fname = build_cv_filename(event_id, company_id, student, slot, file_uploader.name)
    with open(fname, "wb") as f:
        f.write(file_uploader.getbuffer())
    return fname

def _neighbor_slots(slot: str, step: int = 15) -> tuple[str, str]:
    """Return (prev_slot, next_slot) around `slot` with the given step (HH:MM)."""
    dt = datetime.strptime(slot, "%H:%M")
    prev_s = (dt - timedelta(minutes=step)).strftime("%H:%M")
    next_s = (dt + timedelta(minutes=step)).strftime("%H:%M")
    return prev_s, next_s

def book_slot(conn, event_id, company_id, student, slot, cv, matricola=None):
    # --- Block same or adjacent slots for this student across ALL companies ---
    prev_s, next_s = _neighbor_slots(slot, step=15)
    conflict = conn.execute(
        text("""
            SELECT 1 FROM booking
            WHERE event_id = :e AND student = :s
              AND (slot = :slot OR slot = :prev_s OR slot = :next_s)
            LIMIT 1
        """),
        {"e": event_id, "s": student, "slot": slot, "prev_s": prev_s, "next_s": next_s}
    ).first()

    if conflict:
        raise ValueError(
            f"You already have a booking at or adjacent to {slot}. "
            "Please choose a time at least 30 minutes away."
        )

    # --- Proceed with normal insert ---
    conn.execute(
        text("""
            INSERT INTO booking (event_id, company_id, student, slot, cv, status, matricola)
            VALUES (:event_id, :company_id, :student, :slot, :cv, 'manual', :matricola)
            ON CONFLICT(event_id, company_id, student, slot) DO NOTHING
        """),
        {
            "event_id": event_id,
            "company_id": company_id,
            "student": student,
            "slot": slot,
            "cv": cv,
            "matricola": matricola
        }
    )


def get_student_bookings(conn, event_id, student):
    q = text("""
        SELECT b.slot, b.company_id, c.name AS company
        FROM booking b
        JOIN company c ON c.id = b.company_id
        WHERE b.event_id = :e AND b.student = :s
        ORDER BY b.slot
    """)
    return list(conn.execute(q, {"e": event_id, "s": student}).mappings())

# Notifications
def add_notification(conn, event_id, company_id, student, slot_from, kind, message):
    conn.execute(
        text("""INSERT INTO notification (event_id, company_id, student, slot_from, kind, message, created_at)
                VALUES (:e,:c,:s,:slot,:k,:m,:t)"""),
        {"e": event_id, "c": company_id, "s": student, "slot": slot_from,
         "k": kind, "m": message, "t": datetime.utcnow().isoformat()}
    )

def get_unread_notifications(conn, event_id, student):
    q = text("""SELECT id, company_id, slot_from, kind, message, created_at
                FROM notification
                WHERE event_id=:e AND student=:s AND read_at IS NULL
                ORDER BY created_at DESC""")
    return list(conn.execute(q, {"e": event_id, "s": student}).mappings())

def mark_notification_read(conn, notif_id):
    conn.execute(text("UPDATE notification SET read_at=:t WHERE id=:id"),
                 {"t": datetime.utcnow().isoformat(), "id": notif_id})

# Interviews
def get_next_booking(conn, event_id, company_id):
    now = datetime.now().strftime("%H:%M")
    q = text("""SELECT b.id, b.slot, b.student
                FROM booking b
                WHERE b.event_id=:e AND b.company_id=:c AND b.slot >= :now
                ORDER BY b.slot ASC LIMIT 1""")
    return conn.execute(q, {"e": event_id, "c": company_id, "now": now}).mappings().first()

def start_interview(conn, booking_id):
    conn.execute(
        text("""INSERT INTO interview_log (booking_id, start_time, status) 
                VALUES (:b,:t,'active')
                ON CONFLICT(booking_id) DO UPDATE SET start_time=:t, status='active'"""),
        {"b": booking_id, "t": datetime.utcnow().isoformat()}
    )

def end_interview(conn, booking_id):
    now_iso = datetime.utcnow().isoformat()
    conn.execute(
        text("UPDATE interview_log SET end_time=:t, status='done' WHERE booking_id=:b"),
        {"b": booking_id, "t": now_iso}
    )
    b = get_booking_by_id(conn, booking_id)
    if not b:
        return
    slot_start = datetime.strptime(b["slot"], "%H:%M")
    slot_end = slot_start + timedelta(minutes=15)
    now_hm = datetime.strptime(datetime.now().strftime("%H:%M"), "%H:%M")
    if now_hm < slot_end:
        next_slot = (slot_start + timedelta(minutes=15)).strftime("%H:%M")
        nxt = conn.execute(
            text("""SELECT student FROM booking 
                    WHERE event_id=:e AND company_id=:c AND slot=:s"""),
            {"e": b["event_id"], "c": b["company_id"], "s": next_slot}
        ).mappings().first()
        if nxt:
            msg = f"Lo slot precedente ({b['slot']}) con l'azienda è terminato in anticipo. Puoi presentarti ora."
            add_notification(conn, b["event_id"], b["company_id"], nxt["student"], b["slot"], "early_finish", msg)

def mark_no_show(conn, booking_id):
    conn.execute(
        text("UPDATE interview_log SET status='no-show' WHERE booking_id=:b"),
        {"b": booking_id}
    )

def get_bookings_with_logs(conn, event_id, company_id):
    q = text("""
        SELECT 
            b.id,
            b.slot,
            b.student,
            b.cv_path,
            COALESCE(il.status, 'pending') AS status,
            il.start_time,
            il.end_time
        FROM booking b
        LEFT JOIN interview_log il ON il.booking_id = b.id
        WHERE b.event_id = :e AND b.company_id = :c
        ORDER BY b.slot
    """)
    raw_rows = list(conn.execute(q, {"e": event_id, "c": company_id}).mappings())

    def fmt(ts: str | None) -> str:
        if not ts:
            return ""
        return ts[:19].replace("T", " ")

    rows = []
    for rm in raw_rows:
        d = dict(rm)
        d["start_time"] = fmt(d.get("start_time"))
        d["end_time"] = fmt(d.get("end_time"))
        d["cv"] = "✅" if d.get("cv_path") else "—"
        rows.append(d)
    return rows

def get_student_matricola(conn, email):
    """
    Restituisce la matricola dello studente dato l'email
    """
    result = conn.execute(
        text("SELECT matricola FROM student WHERE email = :e"),
        {"e": email.lower().strip()}
    ).scalar()
    return result

def save_student_matricola(conn, givenName, sn, email, matricola, plenary=0, password=None):
    """
    Salva o aggiorna i dati dello studente.
    La password viene aggiornata solo se fornita.
    """
    if password:
        hashed_pw = generate_password_hash(password)
        pw_sql = ", password = :password"
    else:
        hashed_pw = None
        pw_sql = ""

    conn.execute(
        text(f"""
            INSERT INTO student (givenName, sn, email, matricola, plenary_attendance{', password' if password else ''})
            VALUES (:givenName, :sn, :email, :matricola, :plenary_attendance{', :password' if password else ''})
            ON CONFLICT(email) DO UPDATE
            SET givenName = excluded.givenName,
                sn = excluded.sn,
                matricola = excluded.matricola,
                plenary_attendance = excluded.plenary_attendance
                {pw_sql if password else ''}
        """),
        {
            "givenName": givenName,
            "sn": sn,
            "email": email.lower().strip(),
            "matricola": matricola,
            "plenary_attendance": plenary,
            **({"password": hashed_pw} if password else {})
        }
    )


# ------------------- QR helpers (admin) -------------------
try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

def decode_qr_from_image_bytes(image_bytes: bytes) -> list[str]:
    """Return list of decoded QR strings using OpenCV; empty if none/if cv2 missing."""
    if not HAS_CV2:
        return []
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(img)
    if data:
        return [data]
    # multiple
    if hasattr(detector, "detectAndDecodeMulti"):
        ok, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ok and decoded_info:
            return [s for s in decoded_info if s]
    return []

def parse_name_from_qr_text(qr_text: str) -> tuple[str, str, str]:
    """
    Extract (full_name, first_name, last_name) from QR content.
    Supports plain 'Nome Cognome', JSON {"givenName": "...","familyName":"..."} or vCard FN:.
    """
    text_content = qr_text.strip()

    # JSON
    try:
        obj = json.loads(text_content)
        gn = obj.get("givenName") or obj.get("name") or ""
        fn = obj.get("familyName") or obj.get("surname") or ""
        full = (gn + " " + fn).strip() or obj.get("fullName") or ""
        if full:
            return full, gn, fn
    except Exception:
        pass

    # vCard FN:
    m = re.search(r"^FN:(.+)$", text_content, flags=re.MULTILINE)
    if m:
        full = m.group(1).strip()
        parts = full.split()
        if len(parts) >= 2:
            return full, " ".join(parts[:-1]), parts[-1]
        return full, full, ""

    # Plain "Nome Cognome ..."
    parts = re.split(r"\s+", text_content)
    if len(parts) >= 2:
        first = " ".join(parts[:-1])
        last = parts[-1]
        return text_content, first, last

    # Fallback
    return text_content, text_content, ""

def append_attendance_csv(event_id: int, full_name: str, first_name: str, last_name: str, raw_qr: str):
    row = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_id": event_id,
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "raw_qr": raw_qr,
        "source": "qr"
    }
    df_new = pd.DataFrame([row])
    if os.path.exists(ATTENDANCE_CSV):
        try:
            df_old = pd.read_csv(ATTENDANCE_CSV)
            df = pd.concat([df_old, df_new], ignore_index=True)
        except Exception:
            df = df_new
    else:
        df = df_new
    df.to_csv(ATTENDANCE_CSV, index=False)

# --- Running-late notifications (avoid duplicates/spam) ---
def _find_running_late_notif(conn, event_id, company_id, student, slot_from):
    q = text("""SELECT id, message, created_at
                FROM notification
                WHERE event_id=:e AND company_id=:c AND student=:s
                  AND slot_from=:slot AND kind='running_late'
                  AND read_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1""")
    return conn.execute(q, {"e": event_id, "c": company_id, "s": student, "slot": slot_from}).mappings().first()

def upsert_running_late_notification(conn, event_id, company_id, prev_slot, next_student, minutes_late: int):
    """Crea o aggiorna una notifica 'running_late' per il prossimo studente."""
    minutes_late = max(1, int(minutes_late))
    msg = f"The previos slot ({prev_slot}) is late by {minutes_late} min."

    existing = _find_running_late_notif(conn, event_id, company_id, next_student, prev_slot)
    now_iso = datetime.utcnow().isoformat()

    if existing:
        # Aggiorna messaggio e timestamp solo se è cambiato il valore o se è 'vecchia' (>60s)
        try:
            last_ts = datetime.fromisoformat(str(existing["created_at"]))
        except Exception:
            last_ts = None
        should_update = (existing["message"] != msg)
        if last_ts:
            dt = datetime.utcnow() - last_ts
            if dt.total_seconds() > 60:
                should_update = True
        if should_update:
            conn.execute(
                text("UPDATE notification SET message=:m, created_at=:t WHERE id=:id"),
                {"m": msg, "t": now_iso, "id": existing["id"]}
            )
    else:
        conn.execute(
            text("""INSERT INTO notification
                    (event_id, company_id, student, slot_from, kind, message, created_at)
                    VALUES (:e,:c,:s,:slot,'running_late',:m,:t)"""),
            {"e": event_id, "c": company_id, "s": next_student,
             "slot": prev_slot, "m": msg, "t": now_iso}
        )
    
