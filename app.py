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

# Bootstrap SSO se Apache ha già passato attributi
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
    def _get_request_headers():
        """Legge gli header inviati da Apache con Shibboleth"""
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

    with tab_student:
        st.write("**Student Login with UniTN SSO**")
        app_home = "https://ied2025.dii.unitn.it/"

        if AUTH_MODE == "dev":
            # --- flusso dev ---
            email = st.text_input("Institutional email (@unitn.it)", key="student_email")
            if st.button("Login (dev)"):
                if not email.endswith("@unitn.it"):
                    st.error("Use an @unitn.it email valid")
                else:
                    st.session_state["role"] = "student"
                    st.session_state["email"] = email
                    st.session_state["student_name"] = email.split("@")[0]
                    st.success("Login studente simulato (dev mode)")
                    st.rerun()

            # logout dev
            if st.session_state.get("role") == "student":
                if st.button("Logout (dev)"):
                    for k in ["role", "email", "student_name", "givenName", "sn", "idada"]:
                        st.session_state.pop(k, None)
                    st.query_params.clear()
                    st.rerun()

        else:
            # --- flusso produzione ---
            headers = _get_request_headers()
            eppn = headers.get("eppn") or headers.get("X-User-Eppn")

            if eppn:
                st.session_state["role"] = "student"
                st.session_state["student_name"] = eppn  # nome.cognome@unitn.it
                st.session_state["email"] = eppn
                st.success(f"Benvenutə, {st.session_state['student_name']}!")
            else:
                # Nessun attributo: mostra link per avviare SSO
                st.markdown(
                    f'<a href="{app_home}mylogin" target="_self">'
                    '<button style="padding:10px 20px; font-size:16px;">Access with UniTN SSO</button>'
                    '</a>',
                    unsafe_allow_html=True
                )

            # logout
            if st.session_state.get("role") == "student":
                if st.button("Logout"):
                    for k in ["role", "email", "student_name", "givenName", "sn", "idada"]:
                        st.session_state.pop(k, None)
                    st.query_params.clear()
                    st.rerun()

        st.stop()  # blocca l'esecuzione fino al login


# ------------------- TOPBAR -------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"Utente: {st.session_state.get('email','ospite')} • Ruolo: {st.session_state.get('role','none')}")
with col2:
    if st.button("Logout"):
        reset_session()
        st.rerun()


# ------------------- ROUTING -------------------
role = st.session_state.get("role")
if role == "student":
    render_student(event)
elif role == "company":
    render_company(event)
elif role == "admin":
    render_admin(event)
else:
    st.error("Undefined role. Execute logout and a new login.")
