#!/bin/sh
# Starts freshclam and clamd so that the scanner is reachable only once it can
# actually detect something.
#
# The image's own /init is not used. It starts clamd if a database file exists,
# declares itself done when a socket appears, and has no opinion about how old
# that database is or whether it detects anything. Three things this needs
# instead:
#
#   1. a usable signature database before the port opens
#   2. an update attempted at every start, with the outcome decided, not hoped
#   3. a scanner that stops answering rather than answer from a stale database
#
# clamd binds its port only after it has loaded the databases, so the TCP check
# Fly runs cannot pass before step 1 is true. The EICAR self-test below is a
# second proof that what loaded detects.

set -eu

# Overridable only so the tests can run this against stand-in daemons; the
# defaults are where the image keeps them and nothing deployed sets these.
CONF="${CLAMD_CONF_DIR:-/etc/clamav}"
DB="${CLAMD_DB_DIR:-/var/lib/clamav}"
WATCH_INTERVAL="${CLAMD_WATCH_INTERVAL:-30}"
MAX_AGE_DAYS="${CLAMD_MAX_DB_AGE_DAYS:-7}"
START_TIMEOUT="${CLAMD_STARTUP_TIMEOUT:-600}"
UPDATE_TIMEOUT="${FRESHCLAM_TIMEOUT:-120}"

log() { printf '%s koras-clamd: %s\n' "$(date -u +%FT%TZ)" "$*"; }
die() { log "FATAL: $*"; exit 1; }

# Whole days since the daily database last changed. Not the age of the image:
# freshclam rewrites the file when it updates, so this is time since the last
# successful update, which is the thing worth bounding.
db_age_days() {
  f=""
  for c in "$DB/daily.cvd" "$DB/daily.cld"; do [ -s "$c" ] && f="$c"; done
  [ -n "$f" ] || { echo 99999; return; }
  now=$(date +%s)
  mod=$(stat -c %Y "$f")
  echo $(( (now - mod) / 86400 ))
}

# A database is usable when every part clamd needs is present and non-empty.
db_present() {
  for part in main daily bytecode; do
    if [ ! -s "$DB/$part.cvd" ] && [ ! -s "$DB/$part.cld" ]; then
      log "database part missing: $part"
      return 1
    fi
  done
}

db_present || die "no usable signature database; refusing to start"

# --- Update, then decide -----------------------------------------------------
# Bounded: a hung mirror must not hold the machine out of service. The bundled
# database is what runs if this fails, and only while it is fresh enough.
if timeout "$UPDATE_TIMEOUT" freshclam --config-file="$CONF/freshclam.conf" --foreground --stdout; then
  log "signature update succeeded"
else
  age=$(db_age_days)
  if [ "$age" -le "$MAX_AGE_DAYS" ]; then
    log "WARNING: signature update failed; continuing on the existing database, ${age} day(s) old (limit ${MAX_AGE_DAYS})"
  else
    die "signature update failed and the existing database is ${age} day(s) old (limit ${MAX_AGE_DAYS}); refusing to start"
  fi
fi
db_present || die "database unusable after update; refusing to start"

# --- Daemons -----------------------------------------------------------------
freshclam --config-file="$CONF/freshclam.conf" --daemon --foreground --stdout &
FRESH_PID=$!
clamd --config-file="$CONF/clamd.conf" &
CLAMD_PID=$!

# Reachable, then proven. PING only says the process is listening.
waited=0
until [ "$(printf 'PING\n' | nc -w 2 ::1 3310 2>/dev/null || true)" = "PONG" ]; do
  kill -0 "$CLAMD_PID" 2>/dev/null || die "clamd exited during startup"
  [ "$waited" -lt "$START_TIMEOUT" ] || die "clamd not answering after ${START_TIMEOUT}s"
  sleep 2
  waited=$((waited + 2))
done

# The test string is assembled here rather than stored: a file containing it is
# quarantined by every antivirus that reads the repository, this one included.
eicar_a='X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS'
eicar_b='-TEST-FILE!$H+H*'
result=$(printf '%s%s' "$eicar_a" "$eicar_b" | clamdscan --config-file="$CONF/clamd.conf" --stream --no-summary - 2>&1 || true)
if printf '%s' "$result" | grep -qi 'eicar.* FOUND'; then
  log "ready: detection self-test passed"
else
  die "self-test did not detect the test string: $result"
fi

# --- Stay honest -------------------------------------------------------------
# Exits, and so restarts the machine, if either daemon dies or the database
# goes stale. A scanner answering from a months-old database is the failure
# nothing else here would notice.
while :; do
  kill -0 "$CLAMD_PID" 2>/dev/null || die "clamd exited"
  kill -0 "$FRESH_PID" 2>/dev/null || die "freshclam exited"
  age=$(db_age_days)
  [ "$age" -le "$MAX_AGE_DAYS" ] || die "signature database is ${age} day(s) old (limit ${MAX_AGE_DAYS}); updates are failing"
  sleep "$WATCH_INTERVAL"
done
