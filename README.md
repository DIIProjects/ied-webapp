
# Industrial Engineering Day - Streamlit

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
* Student: log in student tab and use your `@unitn` mail. The SSO login is still in progress :

Seed:
- Companies: ENI, Leonardo, FCA, Stellantis.
- Demo company user: `hr@eni.com` / `eni123` (mapped to ENI).

## Local Deploy
* VirtualHosts must be placed in `/etc/apache2/sites-available/`;
* The site is enabled with `a2ensite ieday26`
* Modules must be placed in `/etc/apache2/mods-available/` and they can be enabled by `a2enmod proxy proxy_http headers`
* Apache can be reloaded by `systemctl reload apache2`

### Install requirements
```
sudo apt install -y apache2
sudo a2enmod proxy proxy_http proxy_wstunnel headers ssl rewrite
sudo systemctl enable --now apache2
```

### Create Apache virtual host
```
sudo tee /etc/apache2/sites-available/ied26.conf >/dev/null <<'EOF'
<VirtualHost *:80>
  ServerName ied26
  # Optional extra names:
  # ServerAlias ied26.local ied26.example.edu

  ProxyPreserveHost On
  ProxyPass        /ied26/ http://127.0.0.1:8501/
  ProxyPassReverse /ied26/ http://127.0.0.1:8501/
</VirtualHost>
EOF

```

Then run
```
sudo a2enmod proxy proxy_http headers
sudo a2ensite ieday26
sudo systemctl reload apache2
```

and run the application
```
export STREAMLIT_SERVER_BASE_URL_PATH=/ieday26
streamlit run app.py --server.baseUrlPath=/ieday26 --server.address=127.0.0.1 --server.port=8501
```

## VM deploy
It's all already configured, but here are listed all the steps needed to deploy through the virtual machine.

However, by now it's enough to run the streamlit application by running
```
streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true
```

Then you can find it at this [link](https://ied2025.dii.unitn.it/)


### Previous steps
Let's connect via `ssh` to the virtual machine provided by the university. The, activate a python virtual environment:
```
cd /home/admin/ied-webapp
source .venv/bin/activate
pip install -r requirements.txt
```

Then, install all required packages:
```
sudo apt update
sudo apt install apache2 libapache2-mod-wsgi-py3 python3-venv python3-pip

# Let's enable proxy modules
sudo a2enmod proxy proxy_http proxy_wstunnel ssl headers rewrite
sudo systemctl reload apache2
```

Certificates from `unitn` are stored inside `/etc/ssl/certs/ied2025.dii.unitn.it.crt` and `/etc/ssl/private/ied2025.dii.unitn.it.key`. Their permissions must be updated with
```
sudo chmod 600 /etc/ssl/private/ied2025.dii.unitn.it.key
sudo chmod 644 /etc/ssl/certs/ied2025.dii.unitn.it.crt
```

Then let's configure Apache. Let's create a file
```
sudo nano /etc/apache2/sites-available/ied2025.conf
```
And paste the following configuration
```
<VirtualHost *:80>
  ServerName ied2025.dii.unitn.it
  RewriteEngine On
  RewriteRule ^/(.*)$ https://ied2025.dii.unitn.it/$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
  ServerName ied2025.dii.unitn.it

  SSLEngine on
  SSLCertificateFile /etc/ssl/certs/ied2025.dii.unitn.it.crt
  SSLCertificateKeyFile /etc/ssl/private/ied2025.dii.unitn.it.key

  ProxyRequests Off
  ProxyPreserveHost On
  RequestHeader set X-Forwarded-Proto "https"
  Protocols http/1.1

  ProxyPass        /_stcore/stream ws://127.0.0.1:8501/_stcore/stream
  ProxyPassReverse /_stcore/stream ws://127.0.0.1:8501/_stcore/stream

  ProxyPass        /  http://127.0.0.1:8501/
  ProxyPassReverse /  http://127.0.0.1:8501/

  ErrorLog  /var/log/apache2/ied2025-error.log
  CustomLog /var/log/apache2/ied2025-access.log combined
</VirtualHost>
```

Then reload Apache:
```
sudo a2ensite ied2025
sudo apachectl configtest
sudo systemctl reload apache2
```

> [!WARNING] Remember that you need to have stored in the `ied-webapp` directory the `.env` and `.streamlit/secrets.toml` files. They store the encripted passwords, but they can't be pushed to Github, so you must to create them manually.

Now the application is ready and you can run it with `streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true`. Then you can find it at this [link](https://ied2025.dii.unitn.it/).