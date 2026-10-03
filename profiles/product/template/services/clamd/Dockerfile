# ClamAV, as published by the ClamAV project, pinned by version AND digest.
#
# The digest is the multi-architecture index for 1.4.6 as served by Docker Hub
# on 2026-10-03, confirmed against the registry's Docker-Content-Digest header
# and by pulling the image by digest. A tag can be moved and a digest cannot,
# so this reproduces. 1.4 is the project's long-term-support line.
#
# Bumping it is a commit: change both together, read the release notes, run
# the tests in tests/unit/test_clamd_image.py of the starter's generator suite.
# The image carries a bundled signature database; freshclam updates it at start
# and entrypoint.sh decides what to do when that fails.
FROM clamav/clamav:1.4.6@sha256:57deb108fc4c72778aa83eafbca7bb7153e28c3f57c005afd38d31f16da86f23

# Built from the repository root like every other service, so paths carry the
# service directory. No secret and nothing environment-specific is copied:
# this image is the same bytes in every product and every environment.
COPY services/clamd/clamd.conf /etc/clamav/clamd.conf
COPY services/clamd/freshclam.conf /etc/clamav/freshclam.conf
COPY services/clamd/entrypoint.sh /usr/local/bin/koras-clamd-entrypoint.sh

# Writable by the unprivileged user, which cannot chown what it does not own.
RUN chmod 0755 /usr/local/bin/koras-clamd-entrypoint.sh \
 && chown -R clamav:clamav /var/lib/clamav /tmp

USER clamav

EXPOSE 3310

# The base image ships a check that pings 127.0.0.1, where this clamd does not
# listen (it binds IPv6 only, which is what Fly's private network uses). Fly
# ignores Docker health checks, so this is about plain `docker run`: the same
# check, on the address that is actually bound.
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD [ "$(printf 'PING\n' | nc -w 2 ::1 3310)" = "PONG" ] || exit 1

# tini is the image's own init; keeping it as PID 1 reaps the two daemons and
# receives Fly's stop signal.
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/koras-clamd-entrypoint.sh"]
