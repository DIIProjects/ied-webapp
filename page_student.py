import streamlit as st
from datetime import datetime, timedelta
from sqlalchemy import text, Table, MetaData, update
from auth import find_student_user
from core import _neighbor_slots
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from core import (
    engine,
    get_companies,
    generate_slots,
    get_bookings,
    get_student_bookings,
    save_cv_file,
    book_slot,
    get_unread_notifications,
    mark_notification_read,
    get_roundtables,
    get_student_roundtable_bookings,
    book_roundtable,
)
from auth import find_student_user

# --- CONFIGURAZIONE COLLOQUI ---
MAX_INTERVIEWS_PER_STUDENT = 2       # Limite prenotazioni
LIMIT_ACTIVE_UNTIL = datetime(2025, 11, 11)  # Data fine limite (es. tra qualche giorno)


def student_first_access(email: str):
    """Flusso di primo accesso per lo studente."""
    
    email = email.lower().strip()
    
    # Recupera studente
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)

    if not student:
        st.error("Student not found in the database. Please refer to the administration.")
        st.stop()

    st.title(f"Welcome, {student['givenName']} {student['sn']} 🎓")

    # --- Plenary session ---
    st.subheader("NOTE: to earn the type F credit, you must attend the plenary session")
    plenary_attend = st.checkbox(
        "I will partecipate to the plenary session",
        value=bool(student.get("plenary_attendance"))
    )

    # --- Privacy agreement ---
    st.markdown("""
    #### Privacy Notice
    Your personal data will be processed by the University of Trento in accordance with the Student Privacy Notice, already provided and available on the institutional website at the page “Privacy and Personal Data Protection” (https://www.unitn.it).
    Specifically – and in addition to what is already stated in the Student Privacy Notice – within the framework of the event Industrial Engineering Day 2025, the following personal data: personal details, email address, and, for students who have uploaded it, their CV, will be processed for the purposes referred to under letter (w) of paragraph 3 of the aforementioned notice and shared with the participating companies you have selected.
    """)
    agree_info = st.checkbox("I have read the Information on the processing of personal data.")
    agree_share = st.checkbox(
        "I agree to share my personal data with the participating companies."
    )

    if st.button("💾 Save and continue"):
        # --- Verifica che abbia selezionato la plenary session ---
        if not plenary_attend:
            st.error("⚠️ You must confirm participation to the plenary session to continue.")
        
        elif not agree_info or not agree_share:
            st.error("⚠️ You must accept both privacy statements to continue.")
        
        else:
            # --- Aggiorna database ---
            metadata = MetaData()
            student_table = Table('student', metadata, autoload_with=engine)
            
            stmt = (
                update(student_table)
                .where(student_table.c.email == email)
                .values(plenary_attendance=int(plenary_attend))  # salva 1 se True, 0 se False
            )
            
            with engine.begin() as conn:
                conn.execute(stmt)
            
            st.success("✅ Your privacy agreements have been saved!")
            st.session_state["plenary_done"] = True
            st.rerun()

def send_confirmation_email(student, event):
    """Invia una mail di riepilogo delle prenotazioni allo studente."""
    email = student["email"]
    student_name = f"{student['givenName']} {student['sn']}"

    with engine.begin() as conn:
        # --- Colloqui aziendali ---
        interviews = get_student_bookings(conn, event["id"], email)

        # --- Roundtable bookings ---
        rt_bookings = get_student_roundtable_bookings(conn, event["id"], email)

        # Recupera tutti i roundtable disponibili per questo evento
        result = conn.execute(
            text("SELECT id, name FROM roundtable WHERE event_id = :eid"),
            {"eid": event["id"]}
        )
        all_roundtables = {r.id: r.name for r in result}

    # --- Costruisci testo email ---
    interviews_text = "\n".join(
        f"- {b['company']} at {b['slot']}" for b in interviews
    ) if interviews else "None"

    roundtables_text = "\n".join(
        f"- {all_roundtables.get(b['roundtable_id'], f'Roundtable {b['roundtable_id']}')}"
        for b in rt_bookings
    ) if rt_bookings else "None"

    body = f"""
    Dear {student_name},

    Here is a summary of your current bookings for Industrial Engineering Day 2025:

    🏛️ Plenary session: confirmed

    🏢 Company interviews:
    {interviews_text}

    💬 Round tables:
    {roundtables_text}

    Please make sure to attend all booked sessions.
    Thank you for participating!

    Best regards,
    Industrial Engineering Day Team
    """

    # --- Configurazione email ---
    sender = "noreply@unitn.it"
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = email
    msg["Subject"] = "Your Industrial Engineering Day 2025 Bookings"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.unitn.it", 587) as server:
            server.starttls()
            # server.login("user", "password")  # se serve
            server.send_message(msg)
    except Exception as e:
        st.error(f"❌ Error sending email: {e}")


def render_student(event):
    """Render the Student area."""
    email = st.session_state.get("email")
    if not email:
        st.error("Email not found. Please refer to the administration")
        st.stop()

        # --- Load student from DB first ---
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)
    if not student:
        st.error("Student not found in the database. Please refer to the administration.")
        st.stop()

    # Primo accesso: mostra sempre fino a quando non è salvato in DB
    if student.get("plenary_attendance") is None:
        # Mostra solo se non ha ancora espresso alcuna scelta
        st.session_state.pop("plenary_done", None)
        student_first_access(email)
        st.stop()


    # --- Mostra info studente ---
    with engine.begin() as conn:
        student = find_student_user(email, conn=conn)

    student_name = f"{student['givenName']} {student['sn']}"

    st.markdown(f"### 👤 {student_name}")
    st.info(f"✅ ID student: `{student['matricola']}`")

    tab_companies, tab_roundtables = st.tabs(["Company Interview", "Round Tables"])

    # --- COMPANY INTERVIEWS ---
    with tab_companies:
        st.subheader("Rules to earn the type F credit:")
        st.markdown("""
        - You must attend the plenary session.  
        - You must participate in a round table (bookings available in the next tab).  
        - You must have **at least two interview** with a company.  
        """)
        st.subheader("My Bookings & Notifications")
        
        with engine.begin() as conn:
            # Notifiche non lette
            notifs = get_unread_notifications(conn, event["id"], email)
            for n in notifs:
                colA, colB = st.columns([4, 1])
                with colA:
                    st.info(f"🔔 {n['message']}")
                with colB:
                    if st.button("Mark as read", key=f"read_{n['id']}"):
                        mark_notification_read(conn, n["id"])
                        st.rerun()

            # Prenotazioni studente
            myb = get_student_bookings(conn, event["id"], email)

        st.subheader("My Bookings")
        if myb:
            now = datetime.now()
            for b in myb:
                st.write(f"🕒 {b['slot']} — **{b['company']}**")
        else:
            st.info("No Bookings")

        # --- New Booking ---
        st.subheader("Book an interview - NOTE: bookings cannot be deleted")
        with engine.begin() as conn:
            comps = get_companies(conn, event["id"])

        pick = st.selectbox("Select the company", [c["name"] for c in comps])
        comp_id = next(c["id"] for c in comps if c["name"] == pick)

        with engine.begin() as conn:
            booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}
            myb = get_student_bookings(conn, event["id"], email)

        # --- Filter slots ---
        slots = generate_slots()

        # Block same and adjacent (±15 min) to any existing booking by the student (any company)
        blocked = set()
        for b in myb:
            blocked.add(b["slot"])
            prev_s, next_s = _neighbor_slots(b["slot"], step=15)
            blocked.add(prev_s)
            blocked.add(next_s)

        available = [s for s in slots if s not in booked and s not in blocked]

        if not available:
            st.warning("No slots available for this company.")
            st.stop()

        slot_choice = st.selectbox("Available slots", available)
        cv_link = st.text_input("Optional link / CV", key="cv_link_input")

        # --- Info limite prenotazioni ---
        now = datetime.now()
        limit_active = (
            MAX_INTERVIEWS_PER_STUDENT is not None and
            (LIMIT_ACTIVE_UNTIL is None or now <= LIMIT_ACTIVE_UNTIL)
        )

        if limit_active:
            st.info(
                f"⚙️ Each student can book up to {MAX_INTERVIEWS_PER_STUDENT} interviews "
            )

        # --- Bottone di prenotazione con conferma ---
        if st.button("📅 Book slot"):
            # Salvo i dati della prenotazione in sessione per conferma
            st.session_state["pending_booking"] = {
                "company_name": pick,
                "company_id": comp_id,
                "slot": slot_choice,
                "cv_link": cv_link or None,
                "email": email,
                "matricola": student["matricola"]
            }
            st.rerun()

        # --- Se esiste una prenotazione in attesa, mostra richiesta di conferma ---
        if "pending_booking" in st.session_state:
            pending = st.session_state["pending_booking"]
            st.warning(
                f"⚠️ Do you really want to book an interview with **{pending['company_name']}** "
                f"at **{pending['slot']}**?"
            )
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Confirm booking"):
                    try:
                        with engine.begin() as conn:
                            # Controlla duplicati e limiti
                            myb = get_student_bookings(conn, event["id"], pending["email"])
                            already_with_company = any(b["company"] == pending["company_name"] for b in myb)
                            if already_with_company:
                                st.error(f"⚠️ You have already booked with {pending['company_name']}.")
                            elif limit_active and len(myb) >= MAX_INTERVIEWS_PER_STUDENT:
                                st.error(f"⚠️ You already booked {MAX_INTERVIEWS_PER_STUDENT} interviews.")
                            else:
                                book_slot(
                                    conn,
                                    event["id"],
                                    pending["company_id"],
                                    pending["email"],
                                    pending["slot"],
                                    pending["cv_link"],
                                    pending["matricola"]
                                )
                                st.success(
                                    f"✅ Booking confirmed with {pending['company_name']} at {pending['slot']}!"
                                )
                        del st.session_state["pending_booking"]
                        st.rerun()
                    except Exception as ex:
                        st.error(f"❌ Error during booking: {ex}")
                        del st.session_state["pending_booking"]
                        st.rerun()
            with col2:
                if st.button("❌ Cancel"):
                    del st.session_state["pending_booking"]
                    st.info("Booking cancelled.")
                    st.rerun()


    # --- ROUND TABLES ---
    with tab_roundtables:
        st.subheader("Book a Round Table  9 - 11 am -- The round table booking cannot be deleted")

        # Capacità definite per nome (non per ID)
        CAPACITY_BY_NAME = {
            "Round Table 1": 140,
            "Round Table 2": 140,
            "Round Table 3": 73,
            "Round Table 4": 130,
            "Round Table 5": 113,
            "Round Table 6": 68,
        }

        with engine.begin() as conn:
            roundtables = get_roundtables(conn, event["id"])
            my_rt_bookings = {
                b['roundtable_id'] for b in get_student_roundtable_bookings(conn, event["id"], email)
            }
            current_counts = {
                rt['id']: conn.execute(
                    text("SELECT COUNT(*) FROM roundtable_booking WHERE roundtable_id=:rt_id"),
                    {"rt_id": rt["id"]}
                ).scalar()
                for rt in roundtables
            }

        if my_rt_bookings:
            st.warning("⚠️ You have already booked a round table.")
        else:
            available_roundtables = [
                rt for rt in roundtables
                if current_counts[rt['id']] < CAPACITY_BY_NAME.get(rt['name'], 100)
            ]

            if available_roundtables:
                rt_choice_str = st.selectbox(
                    "Select a round table",
                    [
                        f"{rt['name']} – 📍 {rt['room']} "
                        f"({current_counts[rt['id']]}/{CAPACITY_BY_NAME.get(rt['name'], 100)})"
                        for rt in available_roundtables
                    ]
                )
                rt_choice = next(
                    rt for rt in available_roundtables
                    if rt_choice_str.startswith(rt['name'])
                )

                if st.button("📅 Book this round table"):
                    # Salva i dati per conferma e ricarica la pagina
                    st.session_state["pending_rt_booking"] = {
                        "roundtable_id": rt_choice["id"],
                        "roundtable_name": rt_choice["name"],
                        "room": rt_choice["room"],
                        "email": email,
                        "matricola": student["matricola"]
                    }
                    st.rerun()

        # --- Conferma prenotazione round table (mostrata dopo il rerun) ---
        if "pending_rt_booking" in st.session_state:
            pending_rt = st.session_state["pending_rt_booking"]
            st.warning(
                f"⚠️ Do you really want to book the round table **{pending_rt['roundtable_name']}** "
                f"in room **{pending_rt['room']}**?"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Confirm round table booking"):
                    try:
                        with engine.begin() as conn:
                            already = get_student_roundtable_bookings(conn, event["id"], pending_rt["email"])
                            if already:
                                st.error("⚠️ You have already booked a round table.")
                            else:
                                book_roundtable(
                                    conn,
                                    event["id"],
                                    pending_rt["roundtable_id"],
                                    pending_rt["email"],
                                    pending_rt["matricola"]
                                )
                                st.success(
                                    f"✅ Round table **{pending_rt['roundtable_name']}** booked successfully!"
                                )
                        del st.session_state["pending_rt_booking"]
                        st.rerun()
                    except Exception as ex:
                        st.error(f"❌ Error during booking: {ex}")
                        del st.session_state["pending_rt_booking"]
                        st.rerun()
            with col2:
                if st.button("❌ Cancel"):
                    del st.session_state["pending_rt_booking"]
                    st.info("Round table booking cancelled.")
                    st.rerun()

        # --- Mostra prenotazioni correnti ---
        st.subheader("Your Round Table Bookings")
        if my_rt_bookings:
            for rt in roundtables:
                if rt['id'] in my_rt_bookings:
                    st.write(f"- {rt['name']} – 📍 {rt['room']}")
        else:
            st.info("You have no round table bookings yet.")

