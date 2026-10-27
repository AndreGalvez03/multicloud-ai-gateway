FROM python:3.12-slim@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY app.py /app/app.py
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["python", "/app/app.py"]
