# One image for all demo-app services; SERVICE_NAME picks which one runs.
FROM python:3.12-slim
# iproute2 gives `tc`, used by the fault lab for the network-delay fault.
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
CMD ["sh", "-c", "uvicorn ${SERVICE_NAME}:app --host 0.0.0.0 --port 8000 --log-level warning"]
