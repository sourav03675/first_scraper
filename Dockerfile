FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Required by Back4App
EXPOSE 8080

# Start Gunicorn
CMD ["gunicorn", "-w", "3", "-b", "0.0.0.0:8080", "app:app"]
