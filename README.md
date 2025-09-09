
# Industrial Engineering Day - Streamlit Auth MVP

Login roles:
- **Admin**: user "admin", password "lasolita". Can view all rosters and add companies.
- **Company**: email + password stored in `company_user` table. Sees their roster.
- **Student**: academic email login.
  - DEV mode: simple email/password form requiring @unitn.it email.
  - PROD mode: integrate real SSO (OIDC/SAML) and set `AUTH_MODE='prod'` in `app.py`.

## Run
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Seed:
- Companies: ENI, Leonardo, FCA, Stellantis.
- Demo company user: `hr@eni.com` / `eni123` (mapped to ENI).

Security notes:
- Passwords are stored in cleartext for demo. Replace with hashing (bcrypt/argon2) before production.
- For SSO integration, read the comments in `app.py` (section AUTH / SSO).
