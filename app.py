import streamlit as st
import os
from streamlit_autorefresh import st_autorefresh

from core import engine, init_db, migrate_db, ensure_dirs, get_active_event
from auth import AUTH_MODE, admin_ok, seed_demo_users, reset_session, bootstrap_student_login
from page_student import render_student
from page_company import render_company
from page_admin import render_admin

# ------------------- APP SETUP -------------------
st.set_page_config(page_title="Industrial Engineering Day", page_icon="🎓", layout="centered")

# DB & seed
init_db()
migrate_db()
ensure_dirs()
seed_demo_users()

with engine.begin() as conn:
    event = get_active_event(conn)

# Se l'IdP ha già autenticato e Apache ha passato attributi, facciamo il bootstrap studente.
# La funzione restituisce True SOLO quando imposta effettivamente la sessione per la prima volta.
if bootstrap_student_login():
    st.experimental_rerun()

# refresh solo dopo login (timer colloqui)
if "role" in st.session_state:
    st_autorefresh(interval=1000, key="timer_refresh")

# ------------------- LOGIN VIEW -------------------
if "role" not in st.session_state:
    st.header("Industrial Engineering Day - Login page")
    tab_company, tab_student = st.tabs(["Company", "Student"])

    # late import per evitare circular imports
    from auth import find_company_user

    # --- Company/Admin ---
    with tab_company:
        email = st.text_input("Email", key="company_email")
        pw = st.text_input("Password", type="password", key="company_pass")
        if st.button("Entra", key="btn_company"):
            if admin_ok(email, pw):
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
    # --- helper interno per leggere gli header della tua sessione Streamlit ---
    def _get_request_headers():
        # Funziona da Streamlit 1.20+ (API interna, soggetta a cambiamenti)
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            from streamlit.web.server.server import Server
            ctx = get_script_run_ctx()
            s = Server.get_current()
            if ctx is None or s is None:
                return {}
            session_info = s._session_info_by_id.get(ctx.session_id)
            if session_info is None or session_info.ws is None:
                return {}
            return dict(session_info.ws.request.headers)
        except Exception:
            return {}

    def _post_login_fill_identity():
        # Leggi nome/cognome dagli header impostati da Apache
        hdrs = _get_request_headers()
        st.write("DEBUG headers:", hdrs)  # utile in fase di test
        given = hdrs.get("x-user-givenname") or hdrs.get("X-User-GivenName")
        sn    = hdrs.get("x-user-sn")        or hdrs.get("X-User-SN")
        idada = hdrs.get("x-user-idada")     or hdrs.get("X-User-IdAda")
        if given or sn or idada:
            st.session_state["role"] = "student"
            st.session_state["student_name"] = f"{given or ''} {sn or ''}".strip() or idada
            # Metti anche i campi separati se ti servono:
            st.session_state["givenName"] = given
            st.session_state["sn"] = sn
            st.session_state["idada"] = idada
            return True
        return False

    # --- UI tab ---
    with tab_student:
        st.write("**Student Login with UniTN SSO**")

        AUTH_MODE = os.getenv("AUTH_MODE", "prod")  # o come lo gestisci tu
        app_home = "https://ied2025.dii.unitn.it/"  # cambia se l'app non è sulla root

        # Se siamo già tornati dallo SSO, prova a leggere gli header e completare il login app
        already_ok = _post_login_fill_identity()

        if AUTH_MODE == "dev":
            # --- flusso dev, identico al tuo ---
            email = st.text_input("Istitutional email (@unitn.it)", key="student_email")
            if st.button("Login (dev)"):
                if not email.endswith("@unitn.it"):
                    st.error("Use an @unitn.it email valid")
                else:
                    st.session_state["role"] = "student"
                    st.session_state["email"] = email
                    st.session_state["student_name"] = email.split("@")[0]
                    st.success("Login studente simulato (dev mode)")
                    st.rerun()
        else:
            # --- flusso produzione ---
            if not already_ok:
                st.link_button("Access with UniTN SSO", "https://ied2025.dii.unitn.it/mylogin")
            else:
                st.success(f"Benvenutə, {st.session_state.get('student_name','Studente/a')}!")
    st.stop()

# ------------------- TOPBAR -------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"Utente: {st.session_state.get('email','ospite')} • Ruolo: {st.session_state.get('role','none')}")
with col2:
    if st.button("Logout"):
        reset_session()
        st.rerun()

# ------------------- ROUTING -------------------
role = st.session_state["role"]

if role == "student":
    render_student(event)
elif role == "company":
    render_company(event)
elif role == "admin":
    render_admin(event)
else:
    st.error("Undefined role. Execute logout and a new login.")
