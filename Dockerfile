FROM python:3.14.7-alpine3.23@sha256:6b8f06d04d5305c1d1288435388df9165ab41e681fae6439d6349d8053cc3f83
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH=/app/.venv/bin:$PATH
RUN addgroup -S -g 10001 mcp && adduser -S -D -u 10001 -G mcp -h /app mcp
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.28
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && mkdir -p /state && chown mcp:mcp /state
ENV KEYSSO_STATE_PATH=/state/keysso.sqlite
USER 10001:10001
EXPOSE 8811
ENTRYPOINT ["keysso-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8811"]
