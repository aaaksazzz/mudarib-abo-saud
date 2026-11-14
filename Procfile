web: sh -c 'python -m compileall -q . && exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 240 --graceful-timeout 180 --access-logfile - --error-logfile - app:app'
