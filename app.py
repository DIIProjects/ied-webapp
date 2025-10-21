import streamlit as st
import os

from core import engine, init_db, migrate_db, ensure_dirs, get_active_event
from auth import AUTH_MODE, admin_ok, seed_demo_users, reset_session
from auth import find_student_user, create_student_user, find_company_user, create_student_if_not_exists
from page_student import render_student
from page_company import render_company
from page_admin import render_admin

# ------------------- APP SETUP -------------------
st.set_page_config(page_title="Industrial Engineering Day", page_icon="🎓", layout="centered")

# ------------------- SESSION STATE INIT -------------------
if "role" not in st.session_state:
    st.session_state["role"] = None
if "student_mode" not in st.session_state:
    st.session_state["student_mode"] = "Login"

# ------------------- DB INIT -------------------
init_db()
migrate_db()
ensure_dirs()
seed_demo_users()

with engine.begin() as conn:
    event = get_active_event(conn)

# ------------------- STUDENT BOOTSTRAP (SSO) -------------------
if st.session_state.get("role") is None:
    given = os.environ.get("X_USER_GIVENNAME")
    sn    = os.environ.get("X_USER_SN")
    idada = os.environ.get("X_USER_IDADA")
    eppn  = os.environ.get("X_USER_EPPN")

    if given or sn or idada or eppn:
        st.session_state.update({
            "role": "student",
            "student_name": f"{given or ''} {sn or ''}".strip() or idada or eppn,
            "givenName": given,
            "sn": sn,
            "idada": idada,
            "eppn": eppn
        })

# ------------------- LOGIN VIEW -------------------
if st.session_state.get("role") is None:
    st.header("Industrial Engineering Day - Login page")
    tab_company, tab_student = st.tabs(["Company", "Student"])

    # --- Company/Admin ---
    with tab_company:
        email = st.text_input("Email", key="company_email")
        pw = st.text_input("Password", type="password", key="company_pass")
        if st.button("Entra", key="btn_company"):
            if admin_ok(email, pw):
                st.session_state.update({"role": "admin", "email": "admin@local"})
                st.rerun()
            else:
                with engine.begin() as conn:
                    cu = find_company_user(conn, email, pw)
                if cu:
                    st.session_state.update({
                        "role": "company",
                        "email": cu["email"],
                        "company_id": cu["company_id"]
                    })
                    st.rerun()
                else:
                    st.error("Email o password non corretti")

    # ------------------- LOGIN / REGISTRAZIONE STUDENTI -------------------
    with tab_student:
        st.write("**Student Login / Registration**")

        if AUTH_MODE == "dev":
            email = st.text_input("Email universitaria (@unitn.it)", key="student_dev_email")
            if st.button("Login (dev)"):
                if not email.endswith("@unitn.it"):
                    st.error("Usa una email valida @unitn.it")
                else:
                    with engine.begin() as conn:
                        student = find_student_user(email, conn=conn)
                    if student:
                        st.session_state.update({
                            "role": "student",
                            "email": student["email"],
                            "student_name": f"{student['givenName']} {student['sn']}",
                            "student_id": student["id"]
                        })
                        st.rerun()
                    else:
                        create_student_if_not_exists(
                            email=email.lower().strip(),
                            givenName=email.split("@")[0],
                            sn="",
                            matricola=""
                        )
                        st.session_state.update({
                            "role": "student",
                            "email": email.lower().strip(),
                            "student_name": email.split("@")[0]
                        })
                        st.rerun()

        else:
            mode = st.radio("Seleziona modalità", ["Login", "Registrati"], key="student_mode")

            if mode == "Login":
                email = st.text_input("Email universitaria", key="student_login_email")
                pw = st.text_input("Password", type="password", key="student_login_pw")
                if st.button("Login", key="btn_student_login"):
                    if not email or not pw:
                        st.error("Email e password richieste!")
                    else:
                        with engine.begin() as conn:
                            student = find_student_user(email, pw, conn=conn)
                        if student:
                            st.session_state.update({
                                "role": "student",
                                "email": student["email"],
                                "student_name": f"{student['givenName']} {student['sn']}",
                                "student_id": student["id"]
                            })
                            st.rerun()
                        else:
                            st.error("Email o password non corretti")

            else:  # Registrazione
                st.subheader("Student Registration")
                givenName = st.text_input("Nome", key="student_reg_name")
                sn = st.text_input("Cognome", key="student_reg_surname")
                email = st.text_input("Email universitaria", key="student_reg_email")
                matricola = st.text_input("Matricola", key="student_reg_matricola")
                pw = st.text_input("Password", type="password", key="student_reg_pw")

                if st.button("💾 Registrati"):
                    if not all([givenName.strip(), sn.strip(), email.strip(), matricola.strip(), pw.strip()]):
                        st.error("⚠️ Compila tutti i campi")
                    else:
                        try:
                            create_student_if_not_exists(
                                email=email.lower().strip(),
                                givenName=givenName.strip(),
                                sn=sn.strip(),
                                matricola=matricola.strip(),
                                password=pw.strip()
                            )
                            st.success("✅ Registrazione completata!")
                            st.session_state.update({
                                "role": "student",
                                "email": email.lower().strip(),
                                "student_name": f"{givenName.strip()} {sn.strip()}"
                            })
                            st.rerun()
                        except ValueError as ve:
                            st.error(f"⚠️ {ve}")
                        except Exception as e:
                            st.error(f"Errore durante la registrazione: {e}")

    # 👇 IMPORTANT: stop here so we don't fall through to routing with role=None
    st.stop()

                                                      

# ------------------- TOPBAR + ROUTING -------------------
role = st.session_state.get("role")

if role in ("student", "company", "admin"):
    col1, col2 = st.columns([3, 1])
    with col1:
        # role is guaranteed valid here, so no 'none'
        st.caption(f"Utente: {st.session_state.get('email','')} • Ruolo: {role}")
    with col2:
        if st.button("Logout"):
            reset_session()
            st.rerun()

    if role == "student":
        render_student(event)
    elif role == "company":
        render_company(event)
    elif role == "admin":
        render_admin(event)

# Remove the old final `else: st.error("Undefined role...")`

