# page_student.py
import streamlit as st
import pandas as pd

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
)

def render_student(event):
    """Render the Student area (unchanged behavior)."""
    student = st.session_state.get("student_name") or st.session_state["email"]
    st.title("Area Studente")

    # Notifications + my bookings
    with engine.begin() as conn:
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

        # My bookings
        st.subheader("Le mie prenotazioni")
        myb = get_student_bookings(conn, event["id"], student)

    if myb:
        for b in myb:
            st.write(f"- {b['slot']} con {b['company']}")
    else:
        st.info("Nessuna prenotazione")

    # New booking
    st.subheader("Prenota un nuovo slot")

    with engine.begin() as conn:
        comps = get_companies(conn, event["id"])

    pick = st.selectbox("Scegli azienda", [c["name"] for c in comps])
    comp_id = next(c["id"] for c in comps if c["name"] == pick)

    with engine.begin() as conn:
        booked = {b["slot"] for b in get_bookings(conn, event["id"], comp_id)}

    slots = generate_slots()
    available = [s for s in slots if s not in booked]

    if not available:
        st.warning("Nessuno slot disponibile per questa azienda")
        return

    slot_choice = st.selectbox("Slot disponibili", available)

    # Optional CV
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
