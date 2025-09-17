import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import os
import re
import json
import numpy as np
from streamlit_autorefresh import st_autorefresh

# --- 0) Refresh automatico ogni secondo ---
st_autorefresh(interval=1000, key="timer_refresh")

# Proviamo a importare OpenCV per la lettura QR
try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

DB_URL = "sqlite:///ieday.db"
AUTH_MODE = "dev"  # "dev" simple forms; "prod" integrate UniTN SSO

ADMIN_USER = "admin"
ADMIN_PASS = "lasolita"

ATTENDANCE_CSV = "presenze.csv"  # CSV dove salviamo le presenze da QR
CV_DIR = "cv"

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
  -- nuove colonne per CV (aggiunte via migrazione se non presenti)
  cv_path TEXT,
  cv_uploaded_at TEXT,
  UNIQUE(event_id, company_id, slot)
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
'''

SEED = [
    ("INSERT OR IGNORE INTO event (id, name, is_active) VALUES (1, 'Industrial Engineering Day', 1)", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('ENI')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Leonardo')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('FCA')", {}),
    ("INSERT OR IGNORE INTO company (name) VALUES ('Stellantis')", {}),
    ("INSERT OR IGNORE INTO event_company (event_id, company_id) SELECT 1, c.id FROM company c", {}),
    ("INSERT OR IGNORE INTO company_user (company_id, email, password) "
     "SELECT c.id, 'hr@eni.com', 'eni123' FROM company c WHERE c.name='ENI'", {}),
    ("INSERT OR IGNORE INTO company_user (company_id, email, password) "
     "SELECT c.id, 'leonardo.pasquato@gmail.com', 'cicciopasticcio' FROM company c WHERE c.name='Leonardo'", {}),
]

def init_db():
    with engine.begin() as conn:
        for stmt in SCHEMA.split(';'):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
        for q, p in SEED:
            conn.execute(text(q), p)

def migrate_db():
    """Tenta di aggiungere le colonne per il CV se non esistono già."""
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

# --- Booking helpers ---
def generate_slots(start="09:00", end="17:00", step=15):
    slots = []
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
    # timestamp per unicità
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    return os.path.join(CV_DIR, f"{base}_{ts}{ext}")

def save_cv_file(file_uploader, event_id: int, company_id: int, student: str, slot: str) -> str | None:
    """Salva il file PDF su disco e ritorna il path relativo, oppure None se non caricato."""
    if not file_uploader:
        return None
    ensure_dirs()
    fname = build_cv_filename(event_id, company_id, student, slot, file_uploader.name)
    # Salva bytes
    with open(fname, "wb") as f:
        f.write(file_uploader.getbuffer())
    return fname

def book_slot(conn, event_id, company_id, student, slot, cv_path: str | None = None):
    conn.execute(
        text("""INSERT INTO booking (event_id, company_id, student, slot, cv_path, cv_uploaded_at)
                VALUES (:e,:c,:s,:slot,:cv,:t)"""),
        {
            "e": event_id, "c": company_id, "s": student, "slot": slot,
            "cv": cv_path, "t": datetime.utcnow().isoformat() if cv_path else None
        }
    )

def get_student_bookings(conn, event_id, student):
    q = text("""SELECT b.slot, c.name as company 
                FROM booking b 
                JOIN company c ON c.id=b.company_id 
                WHERE b.event_id=:e AND b.student=:s 
                ORDER BY b.slot""")
    return list(conn.execute(q, {"e": event_id, "s": student}).mappings())

def find_company_user(conn, email, password):
    q = text("""SELECT cu.company_id, cu.email, c.name as company_name 
                FROM company_user cu 
                JOIN company c ON c.id=cu.company_id 
                WHERE cu.email=:e AND cu.password=:p LIMIT 1""")
    return conn.execute(q, {"e": email.strip().lower(), "p": password}).mappings().first()

def add_company(conn, name):
    name = name.strip()
    if not name:
        return False, "Nome azienda vuoto"
    try:
        conn.execute(text("INSERT INTO company (name) VALUES (:n)"), {"n": name})
        ev = get_active_event(conn)
        if ev:
            conn.execute(
                text("""INSERT OR IGNORE INTO event_company (event_id, company_id) 
                        SELECT :e, id FROM company WHERE name=:n"""),
                {"e": ev["id"], "n": name}
            )
        return True, "Azienda aggiunta"
    except Exception as ex:
        return False, f"Errore: {ex}"

def reset_session():
    for k in ("role", "email", "company_id", "student_name"):
        if k in st.session_state:
            del st.session_state[k]

# --- Notifications helpers ---
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

# --- Interview helpers ---
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
    # Close interview
    now_iso = datetime.utcnow().isoformat()
    conn.execute(
        text("UPDATE interview_log SET end_time=:t, status='done' WHERE booking_id=:b"),
        {"b": booking_id, "t": now_iso}
    )

    # Check for early finish and notify next-slot student
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

# --- QR helpers (admin) ---
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
    # Support multiple (rare): try detectAndDecodeMulti if available
    if hasattr(detector, "detectAndDecodeMulti"):
        ok, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ok and decoded_info:
            return [s for s in decoded_info if s]
    return []

def parse_name_from_qr_text(qr_text: str) -> tuple[str, str, str]:
    """
    Try to extract (full_name, first_name, last_name) from QR content.
    Supports plain 'Nome Cognome', JSON {"givenName": "...","familyName":"..."} or vCard FN:.
    Falls back to raw text as full_name.
    """
    text = qr_text.strip()

    # JSON
    try:
        obj = json.loads(text)
        gn = obj.get("givenName") or obj.get("name") or ""
        fn = obj.get("familyName") or obj.get("surname") or ""
        full = (gn + " " + fn).strip() or obj.get("fullName") or ""
        if full:
            return full, gn, fn
    except Exception:
        pass

    # vCard FN:
    m = re.search(r"^FN:(.+)$", text, flags=re.MULTILINE)
    if m:
        full = m.group(1).strip()
        parts = full.split()
        if len(parts) >= 2:
            return full, " ".join(parts[:-1]), parts[-1]
        return full, full, ""

    # Plain "Nome Cognome ..."
    parts = re.split(r"\s+", text)
    if len(parts) >= 2:
        first = " ".join(parts[:-1])
        last = parts[-1]
        return text, first, last

    # Fallback
    return text, text, ""

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

# ------------------- UI -------------------
st.set_page_config(page_title="Industrial Engineering Day", page_icon="🎓", layout="centered")
init_db()
migrate_db()
ensure_dirs()

with engine.begin() as conn:
    event = get_active_event(conn)

# -------- LOGIN VIEW --------
if "role" not in st.session_state:
    st.header("Industrial Engineering Day - Login page")
    tab_company, tab_student = st.tabs(["Company", "Student"])

    # --- Company/Admin ---
    with tab_company:
        email = st.text_input("Email", key="company_email")
        pw = st.text_input("Password", type="password", key="company_pass")
        if st.button("Entra", key="btn_company"):
            if email == ADMIN_USER and pw == ADMIN_PASS:
                st.session_state["role"] = "admin"
                st.session_state["email"] = "admin@local"
                st.success("Login admin ok")
                st.rerun()
            else:
                with engine.begin() as conn:
                    cu = find_company_user(conn, email, pw)
                if cu:
                    st.session_state["role"] = "company"
                    st.session_state["email"] = cu["email"]
                    st.session_state["company_id"] = cu["company_id"]
                    st.success(f"Login azienda: {cu['company_name']}")
                    st.rerun()
                else:
                    st.error("Email o password non corretti")

    # --- Student ---
    with tab_student:
        st.write("**Login studente tramite UniTN**")
        email = st.text_input("Email accademica (@unitn.it)", key="student_email")
        if st.button("Vai al portale UniTN", key="btn_student"):
            if not email.endswith("@unitn.it"):
                st.error("Usa un'email @unitn.it valida")
            else:
                if AUTH_MODE == "dev":
                    st.session_state["role"] = "student"
                    st.session_state["email"] = email
                    st.session_state["student_name"] = email.split("@")[0]
                    st.success("Login studente simulato (dev mode)")
                    st.rerun()
                else:
                    st.markdown(
                        f"[Accedi tramite UniTN SSO](https://idp.unitn.it/idp/profile/SAML2/Redirect/SSO)"
                    )
    st.stop()

# --- TOPBAR ---
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"Utente: {st.session_state.get('email','ospite')} • Ruolo: {st.session_state.get('role','none')}")
with col2:
    if st.button("Logout"):
        reset_session()
        st.rerun()

# --- PAGES ---
role = st.session_state["role"]

if role == "student":
    student = st.session_state.get("student_name") or st.session_state["email"]
    st.title("Area Studente")
    with engine.begin() as conn:
        # --- Notifications banner ---
        notifs = get_unread_notifications(conn, event["id"], student)
        for n in notifs:
            colA, colB = st.columns([4,1])
            with colA:
                st.info(f"🔔 {n['message']}")
            with colB:
                if st.button("Segna letta", key=f"read_{n['id']}"):
                    mark_notification_read(conn, n["id"])
                    st.rerun()

        st.subheader("Le mie prenotazioni")
        myb = get_student_bookings(conn, event["id"], student)
        if myb:
            for b in myb:
                st.write(f"- {b['slot']} con {b['company']}")
        else:
            st.info("Nessuna prenotazione")

        st.subheader("Prenota un nuovo slot")
        comps = get_companies(conn, event["id"])
        pick = st.selectbox("Scegli azienda", [c["name"] for c in comps])
        comp_id = next(c["id"] for c in comps if c["name"] == pick)

        booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}
        slots = generate_slots()
        available = [s for s in slots if s not in booked]

        if not available:
            st.warning("Nessuno slot disponibile per questa azienda")
        else:
            slot_choice = st.selectbox("Slot disponibili", available)

            # --- Upload CV opzionale ---
            st.caption("Carica il tuo CV (PDF, opzionale)")
            cv_file = st.file_uploader("Curriculum (PDF)", type=["pdf"], key="cv_upload")

            if st.button("Prenota slot"):
                try:
                    cv_path = save_cv_file(cv_file, event["id"], comp_id, student, slot_choice)
                    with engine.begin() as conn:
                        book_slot(conn, event["id"], comp_id, student, slot_choice, cv_path)
                    if cv_path:
                        st.success(f"Prenotato {slot_choice} con {pick}. CV caricato.")
                    else:
                        st.success(f"Prenotato {slot_choice} con {pick}.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Errore: {ex}")

elif role == "company":
    st.title("Area Azienda")
    cid = st.session_state.get("company_id")
    if not cid:
        st.error("Nessuna azienda associata all'utente.")
    else:
        # 1) Lettura nome azienda ed evento attivo
        with engine.begin() as conn:
            name = conn.execute(text("SELECT name FROM company WHERE id=:id"), {"id": cid}).scalar()
            event_id = conn.execute(text("SELECT id FROM event WHERE is_active=1 LIMIT 1")).scalar()

        # 2) Booking corrente / prossimo (niente auto-timeout)
        current_id = st.session_state.get("current_booking_id")

        if current_id:
            with engine.begin() as conn:
                current_b = conn.execute(
                    text("SELECT b.id, b.slot, b.student FROM booking b WHERE b.id=:id"),
                    {"id": current_id}
                ).mappings().first()
                if current_b:
                    st_record = conn.execute(
                        text("SELECT status FROM interview_log WHERE booking_id=:b"),
                        {"b": current_b["id"]}
                    ).scalar()
                    if st_record in ("done", "cancelled", "no-show"):
                        st.session_state.pop("current_booking_id", None)
                        st.session_state.pop("started_at", None)
                        current_b = None
        else:
            with engine.begin() as conn:
                current_b = conn.execute(
                    text("""
                        SELECT b.id, b.slot, b.student
                        FROM booking b
                        LEFT JOIN interview_log il ON il.booking_id = b.id
                        WHERE b.event_id = :e
                          AND b.company_id = :c
                          AND (il.status IS NULL OR il.status='pending' OR il.status='active')
                        ORDER BY b.slot ASC
                        LIMIT 1
                    """),
                    {"e": event_id, "c": cid}
                ).mappings().first()

        # 3) UI + Azioni
        st.subheader(f"Prossimo colloquio – {name}")
        if current_b:
            st.markdown(f"### 🕒 {current_b['slot']} – Studente: **{current_b['student']}**")
            colA, colB, colC = st.columns(3)

            # Utility: notifica prossimo slot se presente
            def _notify_next_slot(wconn, event_id_, company_id_, curr_slot: str, kind: str, msg: str):
                try:
                    slot_start = datetime.strptime(curr_slot, "%H:%M")
                    next_slot = (slot_start + timedelta(minutes=15)).strftime("%H:%M")
                    nxt = wconn.execute(
                        text("""SELECT student FROM booking 
                                WHERE event_id=:e AND company_id=:c AND slot=:s"""),
                        {"e": event_id_, "c": company_id_, "s": next_slot}
                    ).mappings().first()
                    if nxt:
                        wconn.execute(
                            text("""INSERT INTO notification 
                                    (event_id, company_id, student, slot_from, kind, message, created_at)
                                    VALUES (:e,:c,:s,:slot,:k,:m,:t)"""),
                            {"e": event_id_, "c": company_id_, "s": nxt["student"],
                             "slot": curr_slot, "k": kind, "m": msg, "t": datetime.utcnow().isoformat()}
                        )
                except Exception:
                    pass

            # ▶️ Inizia (scrive e rerun fuori da callback)
            with colA:
                if st.button("▶️ Inizia", key=f"start_{current_b['id']}", use_container_width=True):
                    with engine.begin() as wconn:
                        wconn.execute(
                            text("""
                                INSERT INTO interview_log (booking_id, start_time, status)
                                VALUES (:b, :t, 'active')
                                ON CONFLICT(booking_id) DO UPDATE SET start_time=:t, status='active'
                            """),
                            {"b": current_b["id"], "t": datetime.utcnow().isoformat()}
                        )
                    st.session_state["current_booking_id"] = current_b["id"]
                    st.session_state["started_at"] = datetime.utcnow().isoformat()
                    st.rerun()

            # ⏹️ Termina (se finito in anticipo, avvisa prossimo)
            with colB:
                if st.button("⏹️ Termina", key=f"end_{current_b['id']}", use_container_width=True):
                    with engine.begin() as wconn:
                        wconn.execute(
                            text("UPDATE interview_log SET end_time=:t, status='done' WHERE booking_id=:b"),
                            {"b": current_b["id"], "t": datetime.utcnow().isoformat()}
                        )
                        slot_start = datetime.strptime(current_b["slot"], "%H:%M")
                        slot_end = slot_start + timedelta(minutes=15)
                        now_hm = datetime.strptime(datetime.now().strftime("%H:%M"), "%H:%M")
                        if now_hm < slot_end:
                            msg = f"Lo slot precedente ({current_b['slot']}) è terminato in anticipo. Puoi presentarti ora."
                            _notify_next_slot(wconn, event_id, cid, current_b["slot"], "early_finish", msg)
                    st.session_state.pop("current_booking_id", None)
                    st.session_state.pop("started_at", None)
                    st.rerun()

            # 🗙 Annulla (sempre avvisa prossimo, nessun timeout automatico)
            with colC:
                if st.button("🗙 Annulla", key=f"cancel_{current_b['id']}", use_container_width=True):
                    with engine.begin() as wconn:
                        wconn.execute(
                            text("""
                                INSERT INTO interview_log (booking_id, end_time, status)
                                VALUES (:b, :t, 'cancelled')
                                ON CONFLICT(booking_id) DO UPDATE SET end_time=:t, status='cancelled'
                            """),
                            {"b": current_b["id"], "t": datetime.utcnow().isoformat()}
                        )
                        msg = f"Lo slot precedente ({current_b['slot']}) è stato annullato. Puoi presentarti ora."
                        _notify_next_slot(wconn, event_id, cid, current_b["slot"], "cancelled_prev", msg)
                    st.session_state.pop("current_booking_id", None)
                    st.session_state.pop("started_at", None)
                    st.rerun()

            # Timer
            started_iso = st.session_state.get("started_at")
            if started_iso:
                started_dt = datetime.fromisoformat(started_iso)
                elapsed = datetime.utcnow() - started_dt
                mins = elapsed.seconds // 60
                secs = elapsed.seconds % 60
                st.markdown(f"⏱ Colloquio in corso: {mins}m {secs}s")

        else:
            st.info("Nessun colloquio disponibile")

        # 4) Tabella prenotazioni aggiornata
        st.subheader("Prenotazioni – Lista completa")
        with engine.begin() as conn:
            rows = conn.execute(text("""
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
            """), {"e": event_id, "c": cid}).mappings().all()

        def fmt(ts: str | None) -> str:
            if not ts:
                return ""
            return ts[:19].replace("T", " ")

        if not rows:
            st.info("Nessuna prenotazione")
        else:
            df = pd.DataFrame([
                {
                    "Orario": r["slot"],
                    "Studente": r["student"],
                    "CV": "✅" if r["cv_path"] else "—",
                    "Stato": r["status"],
                    "Inizio": fmt(r["start_time"]),
                    "Fine": fmt(r["end_time"]),
                    "_id": r["id"],
                    "_cv": r["cv_path"]
                } for r in rows
            ]).sort_values("Orario")
            st.dataframe(df[["Orario","Studente","CV","Stato","Inizio","Fine"]], use_container_width=True)

            st.markdown("**Scarica CV (se disponibile)**")
            for r in df.to_dict("records"):
                if r["_cv"]:
                    try:
                        with open(r["_cv"], "rb") as f:
                            st.download_button(
                                label=f"📄 Scarica CV: {r['Orario']} – {r['Studente']}",
                                data=f.read(),
                                file_name=os.path.basename(r["_cv"]),
                                mime="application/pdf",
                                key=f"dl_{r['_id']}"
                            )
                    except Exception:
                        st.warning(f"CV non trovato su disco per {r['Orario']} – {r['Studente']}")

        # 5) Debug (facoltativo)
        with engine.begin() as conn:
            dbg = conn.execute(text("""
                SELECT booking_id, start_time, end_time, status
                FROM interview_log ORDER BY rowid DESC LIMIT 5
            """)).mappings().all()
        with st.expander("Debug interview_log"):
            st.write(pd.DataFrame(dbg))


elif role == "admin":
    st.title("Area Admin")

    # --- Admin tabs ---
    tab_rosters, tab_add_company, tab_qr = st.tabs(["Rosters", "Aggiungi azienda", "Scanner QR (presenze)"])

    with tab_rosters:
        st.subheader("Rosters (tutte le aziende)")
        with engine.begin() as conn:
            companies = get_companies(conn, event["id"])
            for c in companies:
                st.markdown(f"### {c['name']}")
                rows = get_bookings_with_logs(conn, event["id"], c["id"])
                df = pd.DataFrame(rows)
                if df.empty:
                    st.info("Nessuna prenotazione")
                else:
                    df_show = df.sort_values("slot")[["slot", "student", "cv", "status", "start_time", "end_time"]]
                    df_show = df_show.rename(columns={
                        "slot": "Orario",
                        "student": "Studente",
                        "cv": "CV",
                        "status": "Stato",
                        "start_time": "Inizio",
                        "end_time": "Fine"
                    })
                    st.dataframe(df_show, use_container_width=True)

    with tab_add_company:
        st.subheader("Aggiungi nuova azienda")
        with engine.begin() as conn:
            new_name = st.text_input("Nome azienda", key="new_company_name")
            if st.button("Aggiungi"):
                ok, msg = add_company(conn, new_name)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with tab_qr:
        st.subheader("Scanner QR (presenze studenti)")
        if not HAS_CV2:
            st.error("OpenCV non è installato. Aggiungi 'opencv-python' al requirements.txt e riprova.")
        else:
            st.caption("Scansiona il QR dall'app dell'università (o carica un'immagine).")
            cam_img = st.camera_input("Apri la fotocamera per scannerizzare il QR")
            up_img = st.file_uploader("Oppure carica un'immagine", type=["png", "jpg", "jpeg"])

            image_bytes = None
            if cam_img is not None:
                image_bytes = cam_img.getvalue()
            elif up_img is not None:
                image_bytes = up_img.read()

            if image_bytes:
                decoded_list = decode_qr_from_image_bytes(image_bytes)
                if not decoded_list:
                    st.warning("Nessun QR rilevato nell'immagine.")
                else:
                    for idx, payload in enumerate(decoded_list, start=1):
                        full_name, first_name, last_name = parse_name_from_qr_text(payload)
                        st.success(f"QR #{idx} letto ✅")
                        st.write(f"**Nome completo:** {full_name}")
                        st.write(f"**Nome:** {first_name} — **Cognome:** {last_name}")
                        if st.button(f"Registra presenza (QR #{idx})"):
                            with engine.begin() as conn:
                                append_attendance_csv(event["id"], full_name, first_name, last_name, payload)
                            st.success(f"Presenza registrata su {ATTENDANCE_CSV}")

elif role == "unknown":
    st.error("Ruolo sconosciuto. Eseguire logout e nuovo login.")

else:
    st.error("Ruolo sconosciuto. Eseguire logout e nuovo login.")
