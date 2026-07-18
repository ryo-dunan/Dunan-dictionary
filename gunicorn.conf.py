import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# SQLite serializes writes. One process with several threads is the safest fit
# for the three-person editorial workflow while still serving concurrent reads.
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 60
accesslog = "-"
errorlog = "-"
capture_output = True
