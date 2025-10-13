# page_student.py
import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime, timedelta

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
    get_student_matricola,
    save_student_matricola
)

def render_student(event):
    """Render the Student area."""
    student = st.session_state.get("student_name") or st.session_state["email"]
    st.title("Student Area")

    # --- Carica matricola studente dal DB ---
    with engine.begin() as conn:
        matricola = get_student_matricola(conn, student)

    # Se la matricola non è ancora in sessione, caricala
    if "matricola" not in st.session_state:
        st.session_state["matricola"] = matricola

    st.markdown("### 👤 Student Information")

    # --- Se la matricola non è ancora impostata ---
    if not st.session_state["matricola"]:
        st.warning("🎓 Prima di continuare, inserisci la tua matricola e accetta le informative sulla privacy.")

        # Input per la matricola
        matricola_input = st.text_input("📘 La tua matricola", key="matricola_input")

        st.markdown("---")

        # --- Informativa Privacy ---
        st.markdown("""
        #### Informativa sul trattamento dei dati personali

        I Suoi dati personali verranno trattati dall’**Università di Trento** conformemente all’Informativa sul trattamento dei dati personali degli studenti, già fornita e disponibile alla pagina "Privacy e protezione dei dati personali" del sito istituzionale https://www.unitn.it.

        Nello specifico — e a integrazione di quanto già previsto nell'Informativa sul trattamento dei dati personali degli studenti — nell’ambito dell’evento *Industrial Engineering Day 2025*, i seguenti dati personali: dati anagrafici, email, CV per gli studenti che lo avranno inserito, verranno trattati per le finalità di cui alla lettera w) del paragrafo 3 della medesima informativa e comunicati alle Aziende partecipanti da Lei selezionate.
        """)

        agree_info = st.checkbox("☑️ Dichiaro di aver preso visione dell’Informativa sul trattamento dei dati personali e delle integrazioni sopra riportate.")
        agree_share = st.checkbox("☑️ Richiedo all’Università di Trento, ai sensi dell’art. 96 del d.lgs. 30 giugno 2003, n. 196, che i miei dati personali sopra indicati vengano comunicati alle Aziende da me selezionate.")

        st.markdown("---")

        if st.button("💾 Salva e continua"):
            if not matricola_input.strip():
                st.error("⚠️ Inserisci una matricola valida.")
            elif not agree_info or not agree_share:
                st.error("⚠️ Devi accettare entrambe le dichiarazioni per continuare.")
            else:
                with engine.begin() as conn:
                    # Salva matricola (puoi aggiungere colonne per i consensi se vuoi)
                    save_student_matricola(conn, student, student, matricola_input.strip())
                st.session_state["matricola"] = matricola_input.strip()
                st.success("✅ Matricola e consensi salvati con successo!")
                st.rerun()

        st.stop()

    # --- Se la matricola è già presente ---
    else:
        col1, col2 = st.columns([4, 1])
        with col1:
            st.info(f"👤 **Matricola:** `{st.session_state['matricola']}`")
        with col2:
            if st.button("Edit"):
                st.session_state["matricola"] = None
                st.rerun()


    tab_companies, tab_roundtables = st.tabs(["Company Interview", "Round Tables"])

    with tab_companies:
        st.subheader("My Bookings & Notifications")

        student = st.session_state.get("student_name") or st.session_state["email"]

        # --- Load student bookings ---
        with engine.begin() as conn:
            myb = get_student_bookings(conn, event["id"], student)
            # Notifications
            notifs = get_unread_notifications(conn, event["id"], student)
            for n in notifs:
                colA, colB = st.columns([4, 1])
                with colA:
                    st.info(f"🔔 {n['message']}")
                with colB:
                    if st.button("Segna letta", key=f"read_{n['id']}"):
                        mark_notification_read(conn, n["id"])
                        st.rerun()

            # Student bookings
            myb = get_student_bookings(conn, event["id"], student)

        st.subheader("My Bookings")

        if myb:
            now = datetime.now()
            event_date = event.get("date") or datetime.today().strftime("%Y-%m-%d")

            for b in myb:
                # Parsing dello slot
                try:
                    slot_time = datetime.fromisoformat(b["slot"])
                except ValueError:
                    # slot solo orario, combino con la data dell'evento
                    hour, minute = map(int, b["slot"].split(":"))
                    slot_time = datetime.strptime(event_date, "%Y-%m-%d").replace(hour=hour, minute=minute)

                # Calcolo quanto manca al colloquio in ore
                time_to_interview = (slot_time - now).total_seconds() / 3600

                col1, col2 = st.columns([4, 2])
                with col1:
                    st.write(f"🕒 {b['slot']} — **{b['company']}**")

                with col2:
                    if time_to_interview > 1:
                        if st.button("❌ Delete", key=f"cancel_{b['company']}_{b['slot']}"):
                            try:
                                with engine.begin() as conn:
                                    conn.execute(
                                        text("""
                                            DELETE FROM booking
                                            WHERE event_id = :e AND company_id = :c AND student = :s AND slot = :slot
                                        """),
                                        {
                                            "e": event["id"],
                                            "c": b["company_id"],
                                            "s": student,
                                            "slot": b["slot"]
                                        }
                                    )
                                st.success(f"Booking with {b['company']} at {b['slot']} successfully deleted.")
                                # Forza refresh
                                try:
                                    st.rerun()
                                except Exception:
                                    st.session_state["book_update"] = st.session_state.get("book_update", 0) + 1
                            except Exception as ex:
                                st.error(f"Cancellation error: {ex}")
                    else:
                        # Blocco cancellazione se manca meno di 1 ora
                        st.button("❌ Delete (not available)", key=f"cancel_disabled_{b['company']}_{b['slot']}", disabled=True)
                        st.caption("⏰ It is no longer possible to cancel the reservation (less than 1 hour at the interview).")
        else:
            st.info("No Bookings")

        # --- New Booking ---
        st.subheader("Book an interview")
        with engine.begin() as conn:
            comps = get_companies(conn, event["id"])

        pick = st.selectbox("Select the company", [c["name"] for c in comps])
        comp_id = next(c["id"] for c in comps if c["name"] == pick)

        with engine.begin() as conn:
            booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}
            myb = get_student_bookings(conn, event["id"], student)

        # --- Slot filtering ---
        def parse_slot(slot_str):
            try:
                return datetime.strptime(slot_str, "%H:%M")
            except ValueError:
                return datetime.fromisoformat(slot_str)

        my_booked_times = [parse_slot(b["slot"]) for b in myb]
        slots = generate_slots()
        available = []
        excluded_close = []

        for s in slots:
            if s in booked:
                continue
            s_time = parse_slot(s)
            if any(abs((s_time - t).total_seconds()) < 30*60 for t in my_booked_times):
                excluded_close.append(s)
                continue
            available.append(s)

        if excluded_close:
            st.warning(f"⚠️ {len(excluded_close)} hidden slots because they are too close to reservations already made (±30 min).")
        if not available:
            st.warning("No slots available for this company (considering the 30 minute limit).")
            st.stop()

        slot_choice = st.selectbox("Available slots", available)

        # Optional link
        st.caption("Add a link (optional)")
        cv_link = st.text_input(
            "Link for further information about your experience (GitHub, LinkedIn, Google Drive)",
            key="cv_link_input"
        )

        if st.button("Book slot"):
            try:
                cv_path = cv_link or None
                with engine.begin() as conn:
                    matricola = st.session_state.get("matricola")
                    book_slot(conn, event["id"], comp_id, student, slot_choice, cv_path, matricola)
                st.success(f"Booked {slot_choice} with {pick}. {'CV/link saved.' if cv_link else ''}")
                st.session_state["book_update"] = st.session_state.get("book_update", 0) + 1
            except Exception as ex:
                st.error(f"Errore: {ex}")
   
    with tab_roundtables:
        st.subheader("Book a Round Table")

        student = st.session_state.get("student_name") or st.session_state["email"]

        # Capienza dei tavoli (ID → capienza)
        CAPACITY = {
            1: 140,
            2: 140,
            3: 73,
            4: 130,
            5: 113,
            6: 68,
        }

        with engine.begin() as conn:
            roundtables = get_roundtables(conn, event["id"])
            my_rt_bookings = {b['roundtable_id'] for b in get_student_roundtable_bookings(conn, event["id"], student)}

            # Conta prenotazioni per ogni tavolo
            current_counts = {}
            for rt in roundtables:
                q = text("SELECT COUNT(*) FROM roundtable_booking WHERE roundtable_id = :rt_id")
                current_counts[rt['id']] = conn.execute(q, {"rt_id": rt["id"]}).scalar()

        if not roundtables:
            st.info("No round tables available for this event.")
        else:
            # 🔹 Controllo: studente ha già una prenotazione
            if my_rt_bookings:
                st.warning("⚠️ You have already booked a round table. You can only join one.")
            else:
                # Controlla se tutte hanno raggiunto almeno il 50%
                phase2 = all(current_counts[rt['id']] >= CAPACITY[rt['id']] // 2 for rt in roundtables)

                # Determina roundtable prenotabili
                available_roundtables = []
                for rt in roundtables:
                    limit = CAPACITY[rt['id']] if phase2 else CAPACITY[rt['id']] // 2
                    if current_counts[rt['id']] < limit:
                        available_roundtables.append(rt)

                if not available_roundtables:
                    st.info("No round tables available for booking at this time.")
                else:
                    # Mostra percentuale riempimento
                    options = [
                        f"{rt['name']} – 📍 {rt['room']} ({current_counts[rt['id']]}/{CAPACITY[rt['id']]})"
                        for rt in available_roundtables
                    ]
                    rt_choice_str = st.selectbox("Select a round table", options)

                    if rt_choice_str:
                        rt_choice = next(rt for rt in available_roundtables if rt_choice_str.startswith(rt['name']))

                        if st.button("Book this round table"):
                            try:
                                with engine.begin() as conn:
                                    matricola = st.session_state.get("matricola")
                                    book_roundtable(conn, event["id"], rt_choice['id'], student, matricola)
                                st.success(f"You booked **{rt_choice['name']}** successfully!")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Error while booking: {ex}")

        # --- Mostra prenotazioni correnti ---
        st.subheader("Your Round Table Bookings")
        if my_rt_bookings:
            for rt in roundtables:
                if rt['id'] in my_rt_bookings:
                    st.write(f"- {rt['name']} – 📍 {rt['room']}")
        else:
            st.info("You have no round table bookings yet.")
