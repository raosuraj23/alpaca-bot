FROM python:3.11-slim

WORKDIR /app

# System deps for TA-Lib C library and chromadb native bindings
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget curl \
    && wget -q https://github.com/ta-lib/ta-lib/releases/download/v0.6.4/ta-lib_0.6.4_amd64.deb \
    && dpkg -i ta-lib_0.6.4_amd64.deb \
    && rm ta-lib_0.6.4_amd64.deb \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run Alembic migrations then start uvicorn
CMD alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000
