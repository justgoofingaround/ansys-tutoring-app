# Deploying the Tutoring Hub on meuy4214.poly.edu

Target: the NYU instructor machine (`ay3140@meuy4214.poly.edu`), Docker +
nginx terminating TLS. Unlike the Render demo deployment, this is the real
pilot host: the SQLite database persists on disk in `server_data/`, and
student data never leaves NYU infrastructure.

> **AI IS DISABLED ON THIS HOST** pending the NYU security review.
> `docker-compose.yml` sets `ENABLE_AI=0`, builds with `WITH_COMPASS=0`, and
> runs no Ollama service. With the switch off the app mounts no `/api/chatbot/*`
> routes, forces `ENABLE_LLM` off and ignores `CHATBOT_API_KEY`, so no local or
> cloud generation path exists. Tutorials, quizzes, rubric report checking,
> FAQs and the dashboards are unaffected. See §6 to re-enable after clearance.

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

The cert is issued by Let's Encrypt (certbot) directly on the machine; the
nginx config points at certbot's live directory:

```
/etc/letsencrypt/live/meuy4214.poly.edu/fullchain.pem
/etc/letsencrypt/live/meuy4214.poly.edu/privkey.pem
```

Nothing to copy — the nginx container mounts `/etc/letsencrypt` read-only.

**RENEWAL (action needed before ~60 days after issuance):** the cert was
obtained with certbot in standalone mode, which binds port 80 itself — but
the nginx container now holds port 80, so unattended standalone renewal
WILL fail. Ask the box admin (Chris) to switch the renewal to webroot mode
against the shared volume the nginx container already serves at
`/.well-known/acme-challenge/`, e.g.:

```bash
sudo certbot certonly --cert-name meuy4214.poly.edu --webroot \
  -w /var/lib/docker/volumes/deploy_certbot-webroot/_data --deploy-hook \
  'docker exec tutoring-hub-nginx nginx -s reload'
sudo certbot renew --dry-run    # must pass before trusting the timer
```

## 5. nginx (dockerized)

nginx runs as a compose service (`nginx-docker.conf`), NOT on the host.
Why: the host's SELinux policy blocks host-nginx from proxying to the app
(502, fix needs `setsebool` which our sudo whitelist doesn't allow), and
containers run outside that policy domain. The host nginx must stay
disabled so ports 80/443 are free:

```bash
sudo systemctl disable --now nginx
docker compose --env-file .env up -d --build   # starts hub + nginx together
docker ps                                       # both containers "Up"
curl -sI https://meuy4214.poly.edu/ | head -3   # expect HTTP/2 200
curl -sI http://meuy4214.poly.edu/  | head -3   # expect 301 -> https
```

If the site is unreachable from other campus machines (but curls work on
the box), firewalld may need: `sudo firewall-cmd --permanent
--add-service=http --add-service=https && sudo firewall-cmd --reload`.

Then open https://meuy4214.poly.edu — sign in as the instructor, create a
section under **Class**, and share its `SEC-XXXXXX` code with students.

## 5b. Student registration mail

Students register with their NYU address, and the account only activates when the
emailed confirmation link is opened. Set these in `deploy/.env` (then
`docker compose --env-file .env up -d`):

```
APP_BASE_URL=https://meuy4214.poly.edu
SMTP_HOST=<relay from NYU IT>
SMTP_PORT=587
SMTP_USER=<if the relay needs auth>
SMTP_PASSWORD=<if the relay needs auth>
SMTP_FROM=no-reply@nyu.edu
```

and pass them through in `docker-compose.yml`'s `hub.environment` block.

**If mail cannot be delivered** (this host has restricted egress, so the relay may
not be reachable): leave `SMTP_HOST` unset. The link is then written to the app log
(`docker compose logs hub`), and the instructor can admit each student directly
with the confirm action on the Class page's class list. Registration still works —
only the automatic email is missing.

**Note for the professor:** the link points at `meuy4214.poly.edu`, which only
resolves on the NYU network or VPN, so students should register from a lab machine.

## 6. AI features (disabled — how to re-enable)

Nothing to do for the pilot: the compose file ships with AI off. Verify after a
deploy:

```bash
docker ps                                   # only tutoring-hub + tutoring-hub-nginx
docker exec tutoring-hub pip list | grep -Ei "torch|chromadb|sentence"   # empty
curl -is -X POST https://meuy4214.poly.edu/api/chatbot/query | head -1   # 404/405
```

(A *GET* to an unknown `/api/...` path returns the SPA's index.html by design —
use the POST above when checking that the chatbot is gone.)

### One-time cleanup when switching an AI-enabled host off

```bash
docker rm -f tutoring-hub-ollama            # stop + remove the model server
docker volume rm deploy_ollama-models       # deletes the gemma3:4b weights
mv ~/codebase/ansys-tutoring-app/chatbot_spike/data ~/compass-index-backup
```

The index is not in git, so keep that backup (or the machine that built it) if
Compass may be re-enabled later.

### Re-enabling after security clearance

1. Restore the `ollama` service, `OLLAMA_HOST`, the `ollama-models` volume and
   the `../chatbot_spike/data` bind mount in `docker-compose.yml` (see git
   history for the removed block).
2. Set `ENABLE_AI: "1"` and `ENABLE_LLM: "1"`, and build with
   `WITH_COMPASS: "1"`.
3. Restore `chatbot_spike/data` to the repo on the host *before* building.
4. `docker compose --env-file .env up -d --build`
5. `docker exec tutoring-hub-ollama ollama pull gemma3:4b`

Never set `CHATBOT_API_KEY` on this host — it routes student chat to a cloud
model and breaks the FERPA invariant. Run local Ollama instead.

Without a GPU, generation is CPU-only: expect tens of seconds per request, and
requests queue one at a time. nginx allows 300 s per request
(`proxy_read_timeout` in `nginx-docker.conf`).

## Operations

```bash
docker compose logs -f hub                  # tail app logs
docker compose --env-file .env up -d --build   # redeploy after git pull
docker compose down                          # stop (data persists)
tar czf hub-backup-$(date +%F).tgz ../server_data   # backup everything
```

The webapp is built inside the Docker image (multi-stage Node build), so
the host's node/npm install is not required for deployment.
