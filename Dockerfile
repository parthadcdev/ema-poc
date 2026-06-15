FROM python:3.12-slim
WORKDIR /app
# install deps + package
COPY pyproject.toml ./
COPY ema_poc ./ema_poc
RUN pip install --no-cache-dir .
# config (committed)
COPY config_deploy ./config_deploy
# Optional demo data: baked in for a local `fly deploy` (ema_demo.sqlite is present in
# the build context); ABSENT for a CI checkout (the data is gitignored / not in the
# repo), in which case the app creates an empty DB at startup and the dashboard shows
# empty states until a run is done. The guaranteed pyproject.toml source keeps COPY
# from failing when ema_demo.sqlite is absent; it is then removed.
RUN mkdir -p /app/data
COPY pyproject.toml ema_demo.sqlit[e] /app/data/
RUN rm -f /app/data/pyproject.toml
ENV PORT=8080 PLAYGROUND_MAX_QUERIES_PER_HOUR=60
EXPOSE 8080
# --config-dir is a global flag (defined on the top-level parser), so it must come
# BEFORE the `serve` subcommand or argparse rejects it as "unrecognized arguments".
CMD ["ema", "--config-dir", "config_deploy", "serve", "--host", "0.0.0.0", "--port", "8080"]
