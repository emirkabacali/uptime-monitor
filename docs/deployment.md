# Deployment runbook

Production runs on one Ubuntu LTS VPS with Docker Compose. Caddy terminates HTTPS
(Let's Encrypt) and proxies to the API. GitHub Actions deploys every commit that passes
CI on `main`.

```
GitHub (merge to main) ─► CI: lint, test, build ─► image pushed to GHCR (:latest, :<sha>)
                                     │
                                     ▼ success
                         Deploy workflow ─ SSH ─► server: pull :<sha> → migrate → up -d
                                     │
                                     ▼
                         smoke test: https://<domain>/health and /ready
```

## 1. One-time server setup

1. Rent an Ubuntu 24.04 LTS VPS (1–2 GB RAM is enough) and point a DNS **A record**
   for your domain (e.g. `uptime.example.com`) to the server's IP.
2. Create a dedicated deploy key pair on your computer (no passphrase, used only by
   GitHub Actions):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/uptime_deploy -C "github-actions-deploy" -N ""
   ```
3. Copy `deploy/server-setup.sh` to the server and run it as root. It creates the
   `deploy` user, allows SSH keys only, disables root login, enables `ufw`
   (22, 80, 443 only), unattended security upgrades, fail2ban and Docker:
   ```bash
   scp deploy/server-setup.sh root@SERVER:/root/
   ssh root@SERVER 'DEPLOY_PUBKEY="$(cat)" bash /root/server-setup.sh' < ~/.ssh/uptime_deploy.pub
   ```
4. Create the production configuration **on the server only**:
   ```bash
   scp deploy/.env.production.example deploy@SERVER:uptime-monitor/.env
   ssh deploy@SERVER 'chmod 600 uptime-monitor/.env && nano uptime-monitor/.env'
   ```
   Set `DOMAIN`, and generate `POSTGRES_PASSWORD` and `JWT_SECRET` with
   `openssl rand -base64 48`.

## 2. GitHub configuration

Repository → Settings → Environments → **New environment** `production`, then add:

| Kind | Name | Value |
|---|---|---|
| Secret | `SSH_HOST` | server IP or hostname |
| Secret | `SSH_USER` | `deploy` |
| Secret | `SSH_PRIVATE_KEY` | contents of `~/.ssh/uptime_deploy` (private key) |
| Secret | `SSH_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 SERVER` (pins the host key) |
| Variable | `DOMAIN` | e.g. `uptime.example.com` |

Repository → Settings → Secrets and variables → Actions → Variables:
`DEPLOY_ENABLED` = `true`. Until this variable exists the deploy job is skipped, so CI
stays green before a server exists.

The GHCR package is public (it inherits the public repository), so the server pulls
images without credentials.

## 3. First deploy

Merge anything to `main` (or run the **Deploy** workflow manually with the latest commit
SHA). Caddy requests the certificate on first start; `https://<domain>/docs` should open
with a valid certificate within a minute.

Checks on the server:

```bash
ss -tlnp                       # only 22, 80, 443 listen on public addresses
docker compose -f docker-compose.prod.yml ps
cat ~/uptime-monitor/DEPLOYED_TAG   # commit SHA that is running
```

## 4. Rollback

Every image is tagged with its commit SHA, so rolling back means running an older tag.

- **From GitHub:** Actions → Deploy → *Run workflow* → `image_tag` = the SHA of the last
  good commit.
- **On the server:**
  ```bash
  cd ~/uptime-monitor
  IMAGE_TAG=<good sha> docker compose -f docker-compose.prod.yml up -d
  echo <good sha> > DEPLOYED_TAG
  ```

Database migrations are only applied forwards. A migration that is not backward
compatible must be split into two releases (expand, then contract) so the previous
image keeps working after a rollback.

## 5. Backups

`backup.sh` writes a compressed `pg_dump` to `~/uptime-monitor/backups/` and keeps the
newest 7. Schedule it with cron as the `deploy` user (`crontab -e`):

```
15 2 * * * /home/deploy/uptime-monitor/backup.sh >> /home/deploy/uptime-monitor/backups/backup.log 2>&1
```

A backup only counts once it has been restored. Restore drill (restores into a scratch
database, prints row counts, then drops it):

```bash
./restore.sh backups/<newest>.dump
```

Real disaster recovery: `./restore.sh backups/<file>.dump --replace` (stops the app,
replaces the `uptime` database, starts the app again). Copy backups off the server
regularly (for example to object storage), otherwise losing the server loses the backups.
