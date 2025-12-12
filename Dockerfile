# Merlya - AI-powered infrastructure assistant
# Multi-stage Dockerfile optimized for size and security

# =============================================================================
# Build stage: Install dependencies with uv
# =============================================================================
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy all files needed for the build
COPY pyproject.toml uv.lock README.md ./
COPY merlya/ ./merlya/

# Create virtual environment and install package with dependencies
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python .

# =============================================================================
# Runtime stage: Minimal image with only what's needed
# =============================================================================
FROM python:3.13-slim AS runtime

# Install runtime dependencies (SSH client for key management)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash merlya

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Merlya config directory (can be mounted)
    MERLYA_CONFIG_DIR=/home/merlya/.merlya \
    # Enable offline mode for HuggingFace Hub (model already cached)
    HUGGINGFACE_HUB_OFFLINE=1

# Create config directory
RUN mkdir -p /home/merlya/.merlya && \
    chown -R merlya:merlya /home/merlya /app

# Switch to non-root user
USER merlya

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import merlya; print('OK')" || exit 1

# Default command
ENTRYPOINT ["merlya"]
CMD ["--help"]
