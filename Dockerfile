FROM python:3.12-slim
WORKDIR /app
# install deps + package
COPY pyproject.toml ./
COPY ema_poc ./ema_poc
RUN pip install --no-cache-dir .
# config (committed)
COPY config_deploy ./config_deploy
# Optional demo snapshot baked to /app/seed (NOT /app/data — the Fly volume mounts at
# /app/data and would shadow it). Present for a local `fly deploy` (ema_demo.sqlite is
# in the build context); ABSENT for a CI checkout (gitignored). The guaranteed
# pyproject.toml source keeps COPY from failing when ema_demo.sqlite is absent; it is
# then removed. The entrypoint copies this snapshot onto an empty volume on first boot.
RUN mkdir -p /app/seed
COPY pyproject.toml ema_demo.sqlit[e] /app/seed/
RUN rm -f /app/seed/pyproject.toml
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENV PORT=8080 PLAYGROUND_MAX_QUERIES_PER_HOUR=60
EXPOSE 8080
# Entrypoint auto-seeds the volume, then execs the CMD. --config-dir is a global flag
# (top-level parser), so it must come BEFORE the `serve` subcommand or argparse rejects it.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["ema", "--config-dir", "config_deploy", "serve", "--host", "0.0.0.0", "--port", "8080"]
