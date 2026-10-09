#!/usr/bin/env bash
# Disabled: this legacy root stack's reset is refused, unconditionally.
#
# It ran `docker compose down --volumes --remove-orphans` with no confirmation
# and no check of where docker pointed. Worse, local/docker/shared.compose.yml
# has no top-level `name:`, so the compose project is named after the folder of
# the first -f file -- "docker" -- and `down --volumes` would act on whatever
# other stack on the machine is also called "docker".
#
# The maintained local stack is the one generated projects get
# (profiles/_shared/template/local/scripts/reset.sh), which is guarded. This
# root stack is slated for deprecation (Phase 4, decision A13); until that is
# decided, deleting its data is a deliberate manual act, not a make target:
#
#   docker compose -p docker -f local/docker/shared.compose.yml \
#     -f local/docker/product.compose.yml down --volumes
#
# -- after checking `docker volume ls --filter label=com.docker.compose.project=docker`
# lists only what you mean to delete.
set -euo pipefail

echo "Refusing to reset: the legacy root stack's reset is disabled." >&2
echo "See the comment at the top of local/scripts/reset.sh for why, and for the manual command." >&2
exit 1
