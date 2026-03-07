FROM python:3.11-slim

# Audio tools: sox for reverb, lame for MP3 encoding
# (fluidsynth/abcmidi no longer needed — Lyria outputs WAV directly)
RUN apt-get update && apt-get install -y \
    sox \
    lame \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "--bind", "0.0.0.0:10000", "--timeout", "120", "--workers", "2", "app:app"]
