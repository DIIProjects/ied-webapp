# page_company.py
import os
import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime, timedelta

from core import engine, get_bookings_with_logs, upsert_running_late_notification

def render_company(event):
    """Render the Company area (unchanged behavior)."""
    st.title("Area Azienda")
    cid = st.session_state.get("company_id")
    if not cid:
        st.error("Nessuna azienda associata all'utente.")
        return

    with engine.begin() as conn:
        name = conn.execute(text("SELECT name FROM company WHERE id=:id"), {"id": cid}).scalar()
        event_id = conn.execute(text("SELECT id FROM event WHERE is_active=1 LIMIT 1")).scalar()

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

    # --- Se il colloquio corrente sfora il suo slot, avvisa il prossimo studente con i minuti di ritardo
    if current_b:
        with engine.begin() as wconn:
            st_rec = wconn.execute(
                text("SELECT COALESCE(status, 'pending') FROM interview_log WHERE booking_id=:b"),
                {"b": current_b["id"]}
            ).scalar()
            if st_rec in ("pending", "active"):
                slot_start = datetime.strptime(current_b["slot"], "%H:%M")
                slot_end = slot_start + timedelta(minutes=15)
                now_hm = datetime.strptime(datetime.now().strftime("%H:%M"), "%H:%M")
                if now_hm > slot_end:
                    minutes_late = int((now_hm - slot_end).total_seconds() // 60)
                    next_slot = (slot_start + timedelta(minutes=15)).strftime("%H:%M")
                    nxt = wconn.execute(
                        text("""SELECT student FROM booking 
                                WHERE event_id=:e AND company_id=:c AND slot=:s"""),
                        {"e": event_id, "c": cid, "s": next_slot}
                    ).mappings().first()
                    if nxt:
                        upsert_running_late_notification(
                            wconn, event_id, cid, current_b["slot"], nxt["student"], minutes_late
                        )

    st.subheader(f"Prossimo colloquio – {name}")
    if current_b:
        st.markdown(f"### 🕒 {current_b['slot']} – Studente: **{current_b['student']}**")
        colA, colB, colC = st.columns(3)

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

        started_iso = st.session_state.get("started_at")
        if started_iso:
            started_dt = datetime.fromisoformat(started_iso)
            elapsed = datetime.utcnow() - started_dt
            mins = elapsed.seconds // 60
            secs = elapsed.seconds % 60
            st.markdown(f"⏱ Colloquio in corso: {mins}m {secs}s")
    else:
        st.info("Nessun colloquio disponibile")

    # Table of bookings
    st.subheader("Prenotazioni – Lista completa")
    with engine.begin() as conn:
        rows = get_bookings_with_logs(conn, event["id"], cid)

    def fmt(ts: str | None) -> str:
        if not ts:
            return ""
        return ts[:19].replace("T", " ")

    if not rows:
        st.info("Nessuna prenotazione")
        return

    df = pd.DataFrame([
        {
            "Orario": r["slot"],
            "Studente": r["student"],
            "CV": "✅" if r["cv_path"] else "—",
            "Stato": r["status"],
            "Inizio": fmt(r.get("start_time")),
            "Fine": fmt(r.get("end_time")),
            "_id": r["id"],
            "_cv": r.get("cv_path"),
        } for r in rows
    ]).sort_values("Orario")

    st.dataframe(df[["Orario", "Studente", "CV", "Stato", "Inizio", "Fine"]], use_container_width=True)

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

    # Debug
    with engine.begin() as conn:
        dbg = conn.execute(
            text("SELECT booking_id, start_time, end_time, status FROM interview_log ORDER BY rowid DESC LIMIT 5")
        ).mappings().all()
    with st.expander("Debug interview_log"):
        st.write(pd.DataFrame(dbg))
