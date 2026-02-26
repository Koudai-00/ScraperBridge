FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwrightブラウザと依存パッケージのインストール (Cloud Run用)
RUN playwright install chromium
RUN playwright install-deps chromium
COPY . .
ENV PORT=8080
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 -c gunicorn.conf.py main:app
