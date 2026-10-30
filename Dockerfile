FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data
EXPOSE 8080
CMD ["sh","-c","gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 35 --access-logfile - --error-logfile - app:app"]
