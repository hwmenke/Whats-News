# Production image for the FinDash dashboard.
#   build:  docker build -t findash .
#   run:    docker run -p 8050:8050 -v $(pwd)/data:/data \
#               -e DASHBOARD_PASSWORD=changeme findash
#
# The SQLite DB is written to /data so it survives container restarts.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8050 \
    FINDASH_DB_DIR=/data

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /data

EXPOSE 8050

# 2 workers is plenty for a personal dashboard; bump if you share with others.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8050", "--access-logfile", "-", "app:app"]
