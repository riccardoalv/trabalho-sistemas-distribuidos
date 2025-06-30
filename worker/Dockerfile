FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl \
 && pip install flask prometheus_client \
 && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY app.py .
CMD ["python", "app.py"]
