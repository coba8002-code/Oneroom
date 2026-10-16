# ROOMAX API — 운영 이미지 (deploy/docker-compose.yml 에서 사용)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ROOMAX_UPLOAD_DIR=/data/uploads ROOMAX_BACKUP_DIR=/data/backups
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# root 로 돌리지 않는다. /data = 계약서·안전 백업, /backups = 정기 백업
RUN useradd --system --uid 10001 roomax \
 && mkdir -p /data/uploads /data/backups /backups \
 && chown -R roomax /data /backups
USER roomax
EXPOSE 8000

# 만드는 파일은 소유자만 읽기(umask 077). 시작할 때 마이그레이션을 먼저 적용. 로그인 잠금·메일 발송 제한이 프로세스 메모리에 있으므로 워커는 1개
CMD ["sh", "-c", "umask 077 && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
