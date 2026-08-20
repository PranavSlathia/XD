# XD private operations and rollout

> This is a repository rollout procedure, not evidence that the live Dell has
> already been changed. Preserve Vulture until the parity exit gate below passes.

## Deployment invariants

- `dh-api` binds only to `127.0.0.1:8007`.
- Tailscale Serve is the only remote path. Funnel, Cloudflare Tunnel, router
  forwarding, and `0.0.0.0` binds are forbidden for XD.
- API v1 device authentication stays enabled before Serve is applied.
- The operator worker has no Docker socket and accepts only typed job kinds.
- The system contains no registration, bid, purchase, backorder, or generic
  command endpoint.
- Vulture is not retired during schema/API/client rollout.

## Backend rollout

1. Back up PostgreSQL with `scripts/backup-dh-pg.sh`.
2. Run unit, integration, lint, type, and Alembic drift checks.
3. Apply the migration chain through `20260821_0006_xd_v1_foundations`.
4. Start the default Compose stack. Confirm the legacy API and Vulture still
   work before testing API v1.
5. Generate a short-lived pairing code:

   ```bash
   uv run dh device pairing-code --ttl-minutes 10
   ```

6. Pair each Mac independently. Store each returned token only in that Mac's
   Keychain. Verify that revoking one device does not affect the other.
7. Preview private access without changing Tailscale:

   ```bash
   ./scripts/configure-private-api.sh --dry-run
   ```

8. After confirming the tailnet ACL, apply and verify:

   ```bash
   ./scripts/configure-private-api.sh --apply
   ```

The verification requires `/health` to succeed and an unauthenticated API v1
request to return `401`. Roll back private serving with `tailscale serve reset`;
this does not stop the localhost API.

## Resource guardrails

- The operator/content worker is capped at 256 MB RAM and 0.35 CPU.
- Start with one content job at a time. Add seeds only after their terms and
  robots policy are verified and recorded.
- Keep seed runs bounded by the active versioned crawler configuration.
- If XD's contribution pushes 15-minute Dell load toward 3.0, stop claiming new
  jobs; never terminate an unrelated project.
- Common Crawl graph analysis runs off-Dell. Import compact evidence only.

## Pairing and recovery

- Pairing codes are one-time, short-lived, and stored as salted scrypt hashes.
- Device bearer tokens are generated once; the database stores SHA-256 hashes,
  and raw tokens belong only in macOS Keychain.
- Revoke a lost Mac through API v1 from the remaining paired device, then audit
  candidate events for the revocation.
- If both tokens are lost, generate new pairing codes locally on the Dell. Do
  not weaken `DH_API_V1_AUTH_REQUIRED` as a recovery shortcut.

## Vulture parity exit gate

Run XD and Vulture together for at least 14 consecutive days after the client is
installed. Do not retire Vulture until all are demonstrated:

- identical candidate-event coverage;
- notifications arrive on both Macs and recover after reconnect;
- a read on one Mac is reflected on the other;
- Ready/Research/Reject decisions and reopen actions match server state;
- offline cache is visibly stale and cannot mutate the server;
- pairing/revocation recovery has been rehearsed;
- the four-week engine pilot has enough labelled reviews to evaluate thresholds.

Only then remove the Vulture service in a separate reviewed change and update
the Dell recovery copy. Vulture retirement is not part of the foundation deploy.

