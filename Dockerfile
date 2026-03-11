FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    MCP_STREAMABLE_HTTP_PATH=/mcp \
    GTC_CACHE_DIR=/data/cache

WORKDIR /app

COPY pyproject.toml README.md server.py ./

RUN pip install --no-cache-dir .

VOLUME ["/data"]
EXPOSE 8000

CMD ["gtc-mcp"]
