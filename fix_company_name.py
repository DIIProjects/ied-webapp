from core import engine, text

OLD_NAME = "Infeon Technologies Italia"
NEW_NAME = "Infineon Technologies Italia"

with engine.begin() as conn:
    res = conn.execute(
        text("UPDATE company SET name = :new WHERE name = :old"),
        {"new": NEW_NAME, "old": OLD_NAME}
    )
    print(f"✅ Nome azienda aggiornato: {res.rowcount} riga/e modificate")
