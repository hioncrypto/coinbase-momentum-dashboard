FROM python:3.12-slim

WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static

ENV HOST=0.0.0.0
ENV PORT=8765
EXPOSE 8765

CMD ["python3", "server.py"]
