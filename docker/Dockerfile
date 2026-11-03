# Dockerfile for Inside Airbnb ETL
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv into /bin/
COPY --from=ghcr.io/astral-sh/uv:0.13.6@sha256:8b7774a14bb3abde914fda03efcb83f1f7e9163124e5c13e7fb4cc825293f5fa /uv /bin/uv

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock* ./

# Sync environment without installation the project
RUN uv sync --frozen --no-dev --no-install-project

# Copy project
COPY src/ ./src/
COPY sql/ ./sql/
COPY scripts/ ./scripts/
COPY configs/ ./configs/
COPY .streamlit/ ./.streamlit/

# Default command: run the ETL pipeline. Override to serve the dashboard:
#   command: uv run streamlit run src/dashboard/app.py --server.port 8501
CMD ["uv", "run", "python", "-m", "src.pipeline", "--config", "configs/config.yaml"]