FROM node:14-bullseye-slim AS frontend

WORKDIR /web

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile

COPY postcss.config.js tailwind.config.js tailwind.spacing.js ./
COPY gavel/static/css ./gavel/static/css
COPY gavel/templates ./gavel/templates
COPY gavel/static/js ./gavel/static/js
RUN yarn build


FROM python:3.8-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

WORKDIR /web

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /web/gavel/static/generated.scss ./gavel/static/generated.scss

RUN adduser --disabled-password --gecos "" app \
    && chown -R app:app /web

USER app

EXPOSE 10000

CMD ["sh", "-c", "python initialize.py && exec gunicorn --bind 0.0.0.0:${PORT:-10000} --worker-class eventlet --workers 3 gavel:app"]
