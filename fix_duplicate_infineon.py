from core import engine, text

CORRECT = "Infeon Technologies Italia"      # quella da TENERE
WRONG = "Infineon Technologies Italia"      # quella da ELIMINARE

with engine.begin() as conn:
    correct_id = conn.execute(
        text("SELECT id FROM company WHERE name = :n"), {"n": CORRECT}
    ).scalar()
    wrong_id = conn.execute(
        text("SELECT id FROM company WHERE name = :n"), {"n": WRONG}
    ).scalar()

    print(f"✅ Corretto id={correct_id}, ❌ Sbagliato id={wrong_id}")

    # --- Sposta solo se non c'è già un duplicato per lo stesso event_id ---
    res = conn.execute(text("""
        UPDATE event_company
        SET company_id = :new
        WHERE company_id = :old
          AND event_id NOT IN (
              SELECT event_id FROM event_company WHERE company_id = :new
          )
    """), {"new": correct_id, "old": wrong_id})
    print(f"🔁 Spostati {res.rowcount} collegamenti da event_company senza creare duplicati")

    # --- Ora elimina la vecchia azienda (le righe rimanenti in event_company non causano problemi) ---
    conn.execute(text("DELETE FROM company WHERE id = :id"), {"id": wrong_id})
    print(f"🗑️ Eliminata azienda errata (id={wrong_id})")
