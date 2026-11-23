#!/usr/bin/env bash
# One-time hardening and setup of a fresh Ubuntu LTS server. Run as root:
#
#   DEPLOY_PUBKEY="ssh-ed25519 AAAA... deploy" bash server-setup.sh
#
# Before running: make sure YOUR OWN public key is in /root/.ssh/authorized_keys
# (or the provider's default user), otherwise disabling passwords locks you out.
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
: "${DEPLOY_PUBKEY:?set DEPLOY_PUBKEY to the public key GitHub Actions will use}"

echo "==> System updates and automatic security updates"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
DEBIAN_FRONTEND=noninteractive apt-get -y install unattended-upgrades ufw fail2ban curl ca-certificates
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Non-root user '$DEPLOY_USER' with SSH key login"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER"
fi
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
# Copy the admin's existing keys so the owner can log in as this user too.
if [ -f /root/.ssh/authorized_keys ]; then
  cat /root/.ssh/authorized_keys >> "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi
echo "$DEPLOY_PUBKEY" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"
sort -u -o "/home/$DEPLOY_USER/.ssh/authorized_keys" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/authorized_keys"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"

echo "==> SSH: keys only, no root login, no passwords"
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
CONF
sshd -t
systemctl reload ssh || systemctl reload sshd

echo "==> Firewall: only SSH, HTTP and HTTPS"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw --force enable

echo "==> Docker (official convenience script)"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$DEPLOY_USER"
# Note: Docker-published ports bypass ufw rules. Only Caddy publishes ports
# (80/443) in docker-compose.prod.yml, so nothing else is reachable.

echo "==> Application directory"
install -d -m 750 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/uptime-monitor"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "/home/$DEPLOY_USER/uptime-monitor/backups"

echo "Done. Next: copy .env to /home/$DEPLOY_USER/uptime-monitor/.env (chmod 600)."
