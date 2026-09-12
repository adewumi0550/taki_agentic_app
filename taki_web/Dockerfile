# TAKI farmer chat UI. CPU only, tiny.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --quiet -r requirements.txt
COPY *.py ./
COPY static ./static
EXPOSE 8080
CMD ["python", "app.py"]
