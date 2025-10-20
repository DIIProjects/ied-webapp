import streamlit as st
import os

from core import engine, init_db, migrate_db, ensure_dirs, get_active_event
from auth import AUTH_MODE, admin_ok, seed_demo_users, reset_session
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

# ------------------- STUDENT BOOTSTRAP -------------------
if "role" not in st.session_state:
    # Legge gli header passati da Apache/Shibboleth
    given = os.environ.get("X_USER_GIVENNAME")
    sn    = os.environ.get("X_USER_SN")
    idada = os.environ.get("X_USER_IDADA")
    eppn  = os.environ.get("X_USER_EPPN")

    if given or sn or idada or eppn:
        st.session_state["role"] = "student"
        st.session_state["student_name"] = f"{given or ''} {sn or ''}".strip() or idada or eppn
        st.session_state["givenName"] = given
        st.session_state["sn"] = sn
        st.session_state["idada"] = idada
        st.session_state["eppn"] = eppn

# ------------------- LOGIN VIEW -------------------
if "role" not in st.session_state:
    st.header("Industrial Engineering Day - Login page")
    tab_company, tab_student = st.tabs(["Company", "Student"])

    from auth import find_company_user

    # --- Company/Admin ---
    with tab_company:
        email = st.text_input("Email", key="company_email")
        pw = st.text_input("Password", type="password", key="company_pass")
        if st.button("Entra", key="btn_company"):
            if admin_ok(email, pw):
                st.session_state.update({"role": "admin", "email": "admin@local"})
                st.experimental_rerun()
            else:
                with engine.begin() as conn:
                    cu = find_company_user(conn, email, pw)
                if cu:
                    st.session_state.update({
                        "role": "company",
                        "email": cu["email"],
                        "company_id": cu["company_id"]
                    })
                    st.experimental_rerun()
                else:
                    st.error("Email o password non corretti")

    # --- Student ---
    with tab_student:
        st.write("**Student Login with UniTN SSO**")
        app_home = "https://ied2025.dii.unitn.it/"  # root app

        if AUTH_MODE == "dev":
            email = st.text_input("Institutional email (@unitn.it)", key="student_email")
            if st.button("Login (dev)"):
                if not email.endswith("@unitn.it"):
                    st.error("Use an @unitn.it email valid")
                else:
                    st.session_state.update({
                        "role": "student",
                        "email": email,
                        "student_name": email.split("@")[0]
                    })
                    st.experimental_rerun()

        else:
            # Nessuna sessione: mostra bottone SSO
            st.markdown(
                f'<a href="{app_home}mylogin" target="_self">'
                '<button style="padding:10px 20px; font-size:16px;">Access with UniTN SSO</button>'
                '</a>',
                unsafe_allow_html=True
            )

    st.stop()  # blocca esecuzione finché non loggato

# ------------------- TOPBAR -------------------
col1, col2 = st.columns([3, 1])
with col1:
    st.caption(f"Utente: {st.session_state.get('email','ospite')} • Ruolo: {st.session_state.get('role','none')}")
with col2:
    if st.button("Logout"):
        reset_session()
        st.experimental_rerun()

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
