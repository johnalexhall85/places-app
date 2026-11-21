# CHIP off-VM backup

The nightly encrypted backup to John's Google Drive. It started on 2026-11-21.

## What it does

- **Nightly, at 08:30 UTC (about 3:30 AM Eastern):** [`chip-offsite-backup.sh`](chip-offsite-backup.sh) streams `pg_dump -Fc` of the live `places` database (about 12 GB compressed) through the rclone crypt remote `chip-crypt:`. No local temp file is written.
  - The remote is in the Drive folder `CHIP-backups`, and file names are encrypted too.
  - After each upload, the script reads the dump back with `pg_restore --list` to prove it is complete.
- **Sundays:** the script also keeps a weekly copy and syncs `data/ingest/` (the archived source files) and `data/deploy-recovery/`.
- **Retention:** 7 nightly copies and 4 weekly copies, about 130 GB on Drive.
- **Logs:** `~/.local/state/chip-backup/runs.log` and `journalctl -u chip-offsite-backup`.

## Setup

- The Drive remote `gdrive:` uses `scope=drive.file`, so rclone sees only the files it creates.
- Authorize it once with `rclone config reconnect gdrive:`.
- The two crypt passwords are in `~/.config/chip-backup/RECOVERY-PASSWORDS.txt` (mode 600).
  - **Keep a copy off the VM**, in a password manager.
  - Without these passwords, the backups cannot be read.
  - Never put them in this repository.

## Install

Install from the live checkout:

```bash
sudo cp infra/backup/chip-offsite-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now chip-offsite-backup.timer
```

## Restore on a new machine

1. Install rclone and PostgreSQL with PostGIS.
2. Recreate the two remotes:

   ```bash
   rclone config create gdrive drive scope=drive.file   # opens Google sign-in
   rclone config create chip-crypt crypt remote=gdrive:CHIP-backups \
     filename_encryption=standard directory_name_encryption=true \
     password='<password>' password2='<password2>' --obscure
   ```

3. Find and restore a dump:

   ```bash
   rclone ls chip-crypt:db/daily
   createdb places && psql places -c 'CREATE EXTENSION postgis'
   rclone cat chip-crypt:db/daily/places-<stamp>.dump | pg_restore -d places --no-owner -j 1
   ```

4. Restore the source files with `rclone copy chip-crypt:files/ingest data/ingest`.
