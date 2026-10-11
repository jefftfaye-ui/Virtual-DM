FROM python:3.12-slim

WORKDIR /app

# Install dependencies before copying source (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

# Don't run as root
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8080
CMD ["python", "server.py"]
