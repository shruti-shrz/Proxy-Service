FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY auth_service/ auth_service/
COPY backend_service_a/ backend_service_a/
COPY backend_service_b/ backend_service_b/
COPY reverse_proxy/ reverse_proxy/