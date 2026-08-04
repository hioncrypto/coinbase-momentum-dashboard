FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py /app/server.py
COPY static /app/static
RUN mkdir -p /app/data

ENV HOST=0.0.0.0
ENV PORT=8765
EXPOSE 8765

CMD ["python3", "server.py"]
