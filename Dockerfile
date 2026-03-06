FROM python:3.11-slim

# Install system audio tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    fluidsynth \
    fluid-soundfont-gm \
    abcmidi \
    lame \
    sox \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SOUNDFONT=/usr/share/sounds/sf2/FluidR3_GM.sf2
ENV PORT=10000

EXPOSE 10000

CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2
