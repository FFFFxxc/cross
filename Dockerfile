FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app

ENV HOME=/home/app \
    PATH=/home/app/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TG_DATA_DIR=/home/app/.data

RUN mkdir -p /home/app/src /home/app/.data \
    && chown -R app:app /home/app

USER app
WORKDIR /home/app/src

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app tg_migrator ./tg_migrator

RUN pip install --no-cache-dir --user .

EXPOSE 10000
CMD ["tg-migrator", "watch"]
