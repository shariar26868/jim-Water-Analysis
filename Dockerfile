# # Python 3.11 slim image
# FROM python:3.11-slim

# # Set working directory
# WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y \
#     # PHREEQC dependencies
#     phreeqc \
#     # Poppler for PDF processing
#     poppler-utils \
#     # Build tools
#     gcc \
#     g++ \
#     make \
#     # Clean up
#     && rm -rf /var/lib/apt/lists/*

# # Copy requirements first (for layer caching)
# COPY requirements.txt .

# # Install Python dependencies
# RUN pip install --no-cache-dir --upgrade pip && \
#     pip install --no-cache-dir -r requirements.txt

# # Copy application code
# COPY . .

# # Create necessary directories
# RUN mkdir -p data graphs logs

# # Expose port
# EXPOSE 8000

# # Health check
# HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
#     CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# # Run application
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]




FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies and PHREEQC
RUN apt-get update && apt-get install -y \
    poppler-utils \
    gcc \
    g++ \
    make \
    curl \
    wget \
    gfortran \
    && rm -rf /var/lib/apt/lists/* \
    # Install PHREEQC from official source (updated to version 3.8.6)
    && cd /tmp \
    && wget https://water.usgs.gov/water-resources/software/PHREEQC/phreeqc-3.8.6-17100.tar.gz \
    && tar -xzf phreeqc-3.8.6-17100.tar.gz \
    && cd phreeqc-3.8.6-17100 \
    && ./configure --prefix=/usr \
    && make \
    && make install \
    && cd /tmp \
    && rm -rf phreeqc-* \
    && cd /app

# Copy requirements first (for layer caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data graphs logs

# Expose port
EXPOSE 8000

# Health check - using curl instead of requests for lighter check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application with timeout
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "600", "--reload"]