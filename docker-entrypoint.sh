#!/bin/sh
# Auto-seed the persistent data volume on first boot.
#
# The Fly volume is mounted at /app/data, which starts EMPTY. The demo snapshot is
# baked into the image at /app/seed/ema_demo.sqlite (present only when `fly deploy`
# runs from a working dir that has ema_demo.sqlite — i.e. a local deploy; CI images
# have no seed). If the volume has no DB yet and a baked snapshot exists, copy it in.
# Once seeded, the file persists across every redeploy, so this is a one-time copy and
# later CI deploys never overwrite the live data.
set -e
mkdir -p /app/data
if [ ! -f /app/data/ema_demo.sqlite ] && [ -f /app/seed/ema_demo.sqlite ]; then
  echo "[entrypoint] seeding /app/data/ema_demo.sqlite from baked snapshot"
  cp /app/seed/ema_demo.sqlite /app/data/ema_demo.sqlite
fi
exec "$@"
