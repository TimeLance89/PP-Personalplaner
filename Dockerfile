FROM python:3.12-slim-bookworm
ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --non-unique --gid "${APP_GID}" pp \
    && useradd --non-unique --uid "${APP_UID}" --gid pp --create-home --home-dir /home/pp pp \
    && install -d -o pp -g pp /app/data

WORKDIR /opt/personalplaner
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY --chown=pp:pp . .

ENV PP_DATA_DIR=/app/data \
    PP_HOST=0.0.0.0 \
    PP_PORT=8780 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/pp

EXPOSE 8780
USER pp
CMD ["python", "container_entrypoint.py"]
