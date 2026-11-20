ARG BUILD_FROM
FROM ${BUILD_FROM}

# Ortszeit im Protokoll (wie Add-on 2)
RUN apk add --no-cache tzdata
ENV TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Selbsttest beim Bau: pdfplumber lädt und der Pass-Leser antwortet im Vertrag
RUN python3 -m app.worker --selbsttest

CMD ["python3", "-m", "app.main"]
