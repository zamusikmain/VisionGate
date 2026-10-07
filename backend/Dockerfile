FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY config config
COPY tools tools
RUN useradd --create-home gate && mkdir -p data && chown -R gate:gate /app
USER gate
EXPOSE 8000
CMD ["uvicorn","backend.main:app","--host","0.0.0.0","--port","8000","--workers","2","--limit-concurrency","16"]
