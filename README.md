
# Industrial Engineering Day - Streamlit

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

## Login
* Companies: ENI, Leonardo, FCA, Stellantis, for demo use `hr@eni.com` / `eni123`
* Admin: log in companies tab, use `admin` / `lasolita`
* Student: log in student tab and use your `@unitn` mail. The SSO login is still in progress :)

Seed:
- Companies: ENI, Leonardo, FCA, Stellantis.
- Demo company user: `hr@eni.com` / `eni123` (mapped to ENI).
