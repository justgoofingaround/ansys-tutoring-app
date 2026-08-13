# Deploying the Tutoring Hub on meuy4214.poly.edu

Target: the NYU instructor machine (`ay3140@meuy4214.poly.edu`), Docker +
host nginx terminating TLS. Unlike the Render demo deployment, this is the
real pilot host: the SQLite database persists on disk in `server_data/`,
and student data never leaves NYU infrastructure (FERPA invariant — do NOT
set `CHATBOT_API_KEY` here).

## 1. Get the code onto the machine

```bash
ssh ay3140@meuy4214.poly.edu
git clone <repo-url> ~/ansys-tutoring-app   # or scp/rsync the repo up
cd ~/ansys-tutoring-app
```

## 2. Configure credentials

```bash
cd deploy
cat > .env <<'EOF'
INSTRUCTOR_USERNAME=prof
INSTRUCTOR_PASSWORD=CHANGE-ME
EOF
chmod 600 .env
```

The instructor account is seeded from these on first boot only; changing
them later does not rewrite an existing account.

## 3. Build and start the app container

```bash
docker compose --env-file .env up -d --build
curl -s http://127.0.0.1:8000/ | head -5   # should print the SPA's HTML
```

The container binds to `127.0.0.1:8000` only — nothing is exposed until
nginx fronts it. `../server_data` is bind-mounted, so the database,
uploaded reports, and imported tutorials survive rebuilds and reboots.
First boot seeds the full tutorial + quiz catalog (`SEED_ALL_TUTORIALS=1`).

## 4. TLS certificate

Place the cert + key where the nginx config expects them (or edit the
paths in `nginx-tutoring-hub.conf`):

```bash
sudo mkdir -p /etc/ssl/tutoring-hub
sudo cp fullchain.pem privkey.pem /etc/ssl/tutoring-hub/
sudo chmod 600 /etc/ssl/tutoring-hub/privkey.pem
```

Either an NYU-issued cert for `meuy4214.poly.edu` or Let's Encrypt works
(certbot needs port 80 reachable from the internet; if the host is
campus-only, use the NYU cert).

## 5. nginx

```bash
sudo cp nginx-tutoring-hub.conf /etc/nginx/sites-available/tutoring-hub
sudo ln -s /etc/nginx/sites-available/tutoring-hub /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Then open https://meuy4214.poly.edu — sign in as the instructor, create a
section under **Class**, and share its `SEC-XXXXXX` code with students.

## 6. Later: enable the local-LLM features

AI report review, FAQ drafting, and PDF→tutorial conversion need Ollama on
the host:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:4b        # or the model configured in chatbot_spike
```

Then in `docker-compose.yml`: set `ENABLE_LLM: "1"`, uncomment
`OLLAMA_HOST` and the `extra_hosts` block, and
`docker compose --env-file .env up -d --build`. Real Compass (retrieval
over the indexed Ansys docs) additionally needs the `chatbot_spike/` index
built — see `chatbot_spike/README.md`.

## Operations

```bash
docker compose logs -f hub                  # tail app logs
docker compose --env-file .env up -d --build   # redeploy after git pull
docker compose down                          # stop (data persists)
tar czf hub-backup-$(date +%F).tgz ../server_data   # backup everything
```

The webapp is built inside the Docker image (multi-stage Node build), so
the host's node/npm install is not required for deployment.
