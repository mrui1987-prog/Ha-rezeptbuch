ARG BUILD_FROM
FROM ${BUILD_FROM}

# Ortszeit im Protokoll (Standard Europe/Berlin, Befund B1)
RUN apk add --no-cache tzdata
ENV TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Datenbank und Einstellungen liegen in /data (wird von HA gesichert)
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
