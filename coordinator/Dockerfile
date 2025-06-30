
FROM python:3.12-slim
WORKDIR /app
RUN pip install flask prometheus_client requests
COPY app.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
