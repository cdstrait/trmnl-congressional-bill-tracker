FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_and_push.py .
COPY bills.json .

RUN mkdir -p data

CMD ["python3", "fetch_and_push.py"]
