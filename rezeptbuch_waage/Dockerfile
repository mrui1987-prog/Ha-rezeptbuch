ARG BUILD_FROM
FROM ${BUILD_FROM}

# Ortszeit im Protokoll (Standard Europe/Berlin)
RUN apk add --no-cache tzdata
ENV TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["python3", "-m", "app.main"]
