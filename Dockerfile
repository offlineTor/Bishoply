FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STOCKFISH_PATH=/usr/games/stockfish

WORKDIR /app

# Stockfish is installed from the Debian package so the container does not
# depend on a developer workstation path or a downloaded binary at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       stockfish \
       gcc \
       libstdc++6 \
       ca-certificates \
    && test -x /usr/games/stockfish \
    && apt-get purge -y gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY auth_server.py bot.py ./
COPY backend ./backend

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '10000') + '/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn auth_server:app --host 0.0.0.0 --port ${PORT:-10000}"]
