FROM python:3.12-slim
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data /opt/service \
    && chown app:app /data /opt/service
WORKDIR /opt/service
COPY requirements.txt /opt/service/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . /opt/service/max_reactions
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
HEALTHCHECK --interval=60s --timeout=10s --start-period=90s \
    CMD ["python", "-m", "max_reactions", "health"]
CMD ["python", "-m", "max_reactions", "run"]
