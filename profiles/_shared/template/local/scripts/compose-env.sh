# Sourced, not run: the environment a script needs to `exec`, `ps`, `stop` or
# tear down the local stack.
#
# Compose reads the whole file for every command, and the ZITADEL service
# refuses to load without values only local/scripts/stack.mjs provides (ADR
# 0015). These carry no key and no secret: the masterkey path points at an
# empty file that ZITADEL refuses, so even a `docker compose up` run with them
# fails closed instead of starting anything. Starting the stack is
# `node local/scripts/stack.mjs up`, which supplies the real file after
# verifying it.
#
# Without node or stack.mjs this sets nothing, and compose then fails on its
# own guard with a message naming stack.mjs.
if [ -f "$ROOT/local/scripts/stack.mjs" ] && command -v node >/dev/null 2>&1; then
  _koras_compose_env="$(node "$ROOT/local/scripts/stack.mjs" env --inert)" && eval "$_koras_compose_env"
  unset _koras_compose_env
fi
