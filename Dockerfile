# Образ для запуска переносчика 24/7 на Hugging Face Spaces (SDK: Docker)
# или любом другом Docker-хостинге.
#
# Секреты задаются переменными окружения:
#   TG_API_ID, TG_API_HASH, TG_PHONE, TG_SESSION_STRING,
#   TG_SOURCE, TG_DESTINATION

FROM python:3.12-slim

# Hugging Face Spaces запускает контейнеры от пользователя с UID 1000.
RUN useradd --create-home --uid 1000 app
USER app
ENV HOME=/home/app \
    PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TG_DATA_DIR=/home/app/.data \
    TG_HEALTH_PORT=7860

WORKDIR /home/app/src
COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app tg_migrator ./tg_migrator
RUN pip install --no-cache-dir --user .

EXPOSE 7860
CMD ["tg-migrator", "watch"]
