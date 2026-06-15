FROM python:3.12-slim
WORKDIR /app
# install deps + package
COPY pyproject.toml ./
COPY ema_poc ./ema_poc
RUN pip install --no-cache-dir .
# config (committed) + demo data (from local build context; gitignored, NOT committed)
COPY config_deploy ./config_deploy
COPY ema_demo.sqlite /app/data/ema_demo.sqlite
ENV PORT=8080 PLAYGROUND_MAX_QUERIES_PER_HOUR=60
EXPOSE 8080
CMD ["ema", "serve", "--config-dir", "config_deploy", "--host", "0.0.0.0", "--port", "8080"]
