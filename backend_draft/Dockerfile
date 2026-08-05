FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY seed_problems.json .

ENV DATABASE_PATH=/data/chakrikoi.db
ENV GRANT_SIGNING_SECRET=local-development-secret-change-before-production
ENV RUNNER_ALLOWED_ORIGINS=https://app.chakrikoi.com

VOLUME ["/data"]
EXPOSE 38123
CMD ["gunicorn", "--bind", "0.0.0.0:38123", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "app:APP"]
