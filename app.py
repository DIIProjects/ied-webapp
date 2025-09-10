import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

DB_URL = "sqlite:///ieday.db"
AUTH_MODE = "dev"  # "dev" simple forms; "prod" integrate UniTN SSO

ADMIN_USER = "admin"
ADMIN_PASS = "lasolita"

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
CREATE TABLE IF NOT EXISTS queue_entry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  company_id INTEGER NOT NULL,
  student TEXT NOT NULL,
  position INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TEXT NOT NULL,
  UNIQUE(event_id, company_id, student)
);
CREATE TABLE IF NOT EXISTS company_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL
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

def my_entry(conn, event_id, company_id, student):
    q = text("""SELECT id, position, status 
                FROM queue_entry 
                WHERE event_id=:e AND company_id=:c AND student=:s 
                  AND status='queued' LIMIT 1""")
    return conn.execute(q, {"e": event_id, "c": company_id, "s": student}).mappings().first()

def queue_len(conn, event_id, company_id):
    return conn.execute(
        text("SELECT COUNT(*) FROM queue_entry WHERE event_id=:e AND company_id=:c AND status='queued'"),
        {"e": event_id, "c": company_id}
    ).scalar_one()

def join_queue(conn, event_id, company_id, student):
    if my_entry(conn, event_id, company_id, student):
        return
    last = conn.execute(
        text("SELECT MAX(position) FROM queue_entry WHERE event_id=:e AND company_id=:c"),
        {"e": event_id, "c": company_id}
    ).scalar()
    next_pos = (last or 0) + 1
    conn.execute(
        text("""INSERT INTO queue_entry (event_id, company_id, student, position, status, created_at) 
                VALUES (:e,:c,:s,:p,'queued',:t)"""),
        {"e": event_id, "c": company_id, "s": student, "p": next_pos, "t": datetime.utcnow().isoformat()}
    )

def leave_queue(conn, event_id, company_id, student):
    conn.execute(
        text("""UPDATE queue_entry SET status='cancelled' 
                WHERE event_id=:e AND company_id=:c AND student=:s AND status='queued'"""),
        {"e": event_id, "c": company_id, "s": student}
    )

def roster_df(conn, event_id, company_id):
    rows = conn.execute(
        text("""SELECT position AS Posizione, student AS Studente, created_at AS Inserito
                FROM queue_entry
                WHERE event_id = :e AND company_id = :c AND status = 'queued'
                ORDER BY position ASC"""),
        {"e": event_id, "c": company_id}
    ).mappings().all()
    return pd.DataFrame(rows)

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

# ------------------- UI -------------------
st.set_page_config(page_title="Industrial Engineering Day", page_icon="🎓", layout="centered")
init_db()

with engine.begin() as conn:
    event = get_active_event(conn)

# -------- LOGIN VIEW --------
if "role" not in st.session_state:
    st.header("Login")
    tab_company, tab_student = st.tabs(["Company", "Student"])

    # --- Azienda/Admin ---
    with tab_company:
        email = st.text_input("Email", key="company_email")
        pw = st.text_input("Password", type="password", key="company_pass")
        if st.button("Entra", key="btn_company"):
            # Admin
            if email == ADMIN_USER and pw == ADMIN_PASS:
                st.session_state["role"] = "admin"
                st.session_state["email"] = "admin@local"
                st.success("Login admin ok")
                st.rerun()
            else:
                # Azienda
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

    # --- Studente ---
    with tab_student:
        st.write("**Login studente tramite UniTN**")
        email = st.text_input("Email accademica (@unitn.it)", key="student_email")
        if st.button("Vai al portale UniTN", key="btn_student"):
            if not email.endswith("@unitn.it"):
                st.error("Usa un'email @unitn.it valida")
            else:
                if AUTH_MODE == "dev":
                    # Simulazione: login diretto
                    st.session_state["role"] = "student"
                    st.session_state["email"] = email
                    st.session_state["student_name"] = email.split("@")[0]
                    st.success("Login studente simulato (dev mode)")
                    st.rerun()
                else:
                    # Produzione: redirect verso SSO UniTN (link di esempio)
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
        st.subheader("Check-in")
        checked = is_checked_in(conn, event["id"], student)
        colA, colB = st.columns(2)
        with colA:
            st.write("✅ Check-in effettuato" if checked else "Non hai fatto il check-in")
        with colB:
            if checked:
                if st.button("Annulla check-in"):
                    toggle_checkin(conn, event["id"], student)
                    st.rerun()
            else:
                if st.button("Effettua check-in"):
                    toggle_checkin(conn, event["id"], student)
                    st.rerun()

        st.subheader("Aziende")
        for c in get_companies(conn, event["id"]):
            col1, col2, col3 = st.columns([3, 2, 2])
            with col1:
                st.write(f"**{c['name']}**")
            with col2:
                st.caption(f"In coda: {queue_len(conn, event['id'], c['id'])}")
            with col3:
                entry = my_entry(conn, event["id"], c["id"], student)
                if entry:
                    if st.button(f"Esci (#{entry['position']})", key=f"leave_{c['id']}"):
                        with engine.begin() as inner:
                            leave_queue(inner, event["id"], c["id"], student)
                        st.rerun()
                else:
                    if st.button("Metti in coda", key=f"join_{c['id']}"):
                        with engine.begin() as inner:
                            join_queue(inner, event["id"], c["id"], student)
                        st.rerun()

elif role == "company":
    st.title("Area Azienda")
    cid = st.session_state.get("company_id")
    if not cid:
        st.error("Nessuna azienda associata all'utente.")
    else:
        with engine.begin() as conn:
            name = conn.execute(
                text("SELECT name FROM company WHERE id=:id"), {"id": cid}
            ).scalar()
            st.subheader(f"Coda – {name}")
            df = roster_df(conn, event["id"], cid)
            st.dataframe(df, use_container_width=True)

elif role == "admin":
    st.title("Area Admin")
    st.subheader("Rosters (tutte le aziende)")
    with engine.begin() as conn:
        companies = get_companies(conn, event["id"])
        for c in companies:
            st.markdown(f"### {c['name']}")
            df = roster_df(conn, event["id"], c["id"])
            st.dataframe(df, use_container_width=True)

    st.markdown("---")
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

    st.markdown("---")
    st.subheader("Gestione demo")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Reset code (tutte le code vuote)"):
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM queue_entry"))
            st.success("Code svuotate")
    with col2:
        if st.button("Reset check-in"):
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM checkin"))
            st.success("Check-in cancellati")

else:
    st.error("Ruolo sconosciuto. Eseguire logout e nuovo login.")
