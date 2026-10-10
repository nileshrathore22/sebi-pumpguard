FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 1000 pumpguard
COPY --chown=pumpguard:pumpguard . .
RUN mkdir -p artifacts && chown pumpguard:pumpguard artifacts && chmod +x docker/*.sh
USER pumpguard

EXPOSE 8000 8501
CMD ["docker/api-entrypoint.sh"]
