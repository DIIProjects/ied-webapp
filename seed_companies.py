import csv
from core import engine
from auth import make_hash
from sqlalchemy import text

CSV_FILE = "companies.csv"

# Legge il CSV
with open(CSV_FILE, newline="") as f:
    reader = csv.DictReader(f)
    companies = list(reader)

created_users = []
updated_users = []
skipped_users = []

with engine.begin() as conn:
    for comp in companies:
        name = comp["company_name"].strip()
        email = comp["email"].strip().lower()
        pw = comp["password"].strip()
        pw_hash = make_hash(pw)

        # 1️⃣ Inserisci azienda se non esiste
        company_id = conn.execute(
            text("SELECT id FROM company WHERE name=:n"), {"n": name}
        ).scalar()
        if not company_id:
            conn.execute(
                text("INSERT INTO company (name) VALUES (:n)"), {"n": name}
            )
            company_id = conn.execute(
                text("SELECT id FROM company WHERE name=:n"), {"n": name}
            ).scalar()
            print(f"🟢 Azienda '{name}' creata.")
        else:
            print(f"🔵 Azienda '{name}' già esistente.")

        # 2️⃣ Inserisci o aggiorna utente
        row = conn.execute(
            text("SELECT id, password FROM company_user WHERE LOWER(email)=:e"),
            {"e": email}
        ).mappings().first()

        if row:
            # Aggiorna password se diversa
            if row["password"] != pw_hash:
                conn.execute(
                    text("UPDATE company_user SET password=:p WHERE id=:id"),
                    {"p": pw_hash, "id": row["id"]}
                )
                updated_users.append(email)
                print(f"🟡 Password aggiornata per '{email}'.")
            else:
                skipped_users.append(email)
                print(f"⚪ Nessuna modifica per '{email}'.")
        else:
            # Inserisci nuovo user
            conn.execute(
                text(
                    "INSERT INTO company_user (company_id, email, password) "
                    "VALUES (:cid, :e, :p)"
                ),
                {"cid": company_id, "e": email, "p": pw_hash}
            )
            created_users.append(email)
            print(f"🟢 Utente '{email}' creato.")

# Riepilogo finale
print("\n✅ Riepilogo:")
print(f"🟢 Utenti creati: {len(created_users)} -> {created_users}")
print(f"🟡 Password aggiornate: {len(updated_users)} -> {updated_users}")
print(f"⚪ Nessuna modifica: {len(skipped_users)} -> {skipped_users}")
