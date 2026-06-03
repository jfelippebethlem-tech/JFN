FROM python:3.12-slim

# Evita prompts e bytecode órfão; logs sem buffer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependências primeiro, para aproveitar o cache de camadas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mestre_yoda ./mestre_yoda

# Roda sem privilégios.
RUN useradd --create-home yoda
USER yoda

# A memória persiste em /data (monte um volume aqui).
ENV YODA_DB_PATH=/data/yoda_memory.db
VOLUME ["/data"]

CMD ["python", "-m", "mestre_yoda"]
