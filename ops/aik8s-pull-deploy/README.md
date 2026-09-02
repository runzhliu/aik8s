# Server-pull deployment

The production server polls the public `site-production` GitHub Release and
pulls the generated static site over outbound HTTPS. GitHub-hosted runners do
not connect to the server.

The workflow publishes the tarball, checksum, and manifest first. It replaces
`revision.txt` last as a commit marker. The server then:

1. detects a new 40-character Git revision;
2. downloads and verifies the matching artifact;
3. extracts it into `/srv/aik8s/releases/<revision>`;
4. atomically changes `/srv/aik8s/current`;
5. checks `https://aik8s.run/` through the local HTTPS listener and rolls back
   the symlink if that check fails.

The Caddy container mounts `/srv/aik8s` read-only, so activation does not need
a container restart. The systemd service runs as the unprivileged
`aik8s-deploy` user and can only write below `/srv/aik8s`.

## Bootstrap

Install the script and units as root, then create the deploy user and transfer
ownership of only the deployment root and releases parent:

```bash
useradd --system --home-dir /srv/aik8s --shell /usr/sbin/nologin aik8s-deploy
install -o root -g root -m 0755 aik8s-pull-deploy.sh /usr/local/sbin/aik8s-pull-deploy
install -o root -g root -m 0644 aik8s-pull-deploy.service /etc/systemd/system/
install -o root -g root -m 0644 aik8s-pull-deploy.timer /etc/systemd/system/
chown aik8s-deploy:aik8s-deploy /srv/aik8s /srv/aik8s/releases
chown -h aik8s-deploy:aik8s-deploy /srv/aik8s/current
systemctl daemon-reload
systemctl enable --now aik8s-pull-deploy.timer
```

Run an immediate check and inspect its logs with:

```bash
systemctl start aik8s-pull-deploy.service
journalctl -u aik8s-pull-deploy.service --since today
```

To roll back manually, atomically point `/srv/aik8s/current` at a known-good
directory under `/srv/aik8s/releases`. The puller intentionally does not delete
old releases.
