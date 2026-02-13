#!/bin/bash
# Start script for Standalone Insurance Voice Agent

set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "=========================================="
echo "🎙️  Insurance Voice Agent"
echo "=========================================="

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run: ./scripts/setup.sh"
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check required environment variables
missing_vars=0

if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY is not set in .env"
    missing_vars=1
fi

if [ $missing_vars -eq 1 ]; then
    echo ""
    echo "Please configure .env file with required variables"
    exit 1
fi

# Show configuration
echo "Configuration:"
echo "  Domain: ${YOUR_DOMAIN:-localhost}"
echo "  Port: ${PORT:-5000}"
echo "  Log Level: ${LOG_LEVEL:-INFO}"
echo ""

echo "=========================================="
echo "🚀 Starting server..."
echo "=========================================="

# Start server
if [ "$1" == "prod" ]; then
    echo "Starting in production mode with gunicorn..."
    gunicorn --bind 0.0.0.0:${PORT:-5000} \
             --workers 4 \
             --worker-class sync \
             --timeout 300 \
             --log-level info \
             --access-logfile logs/access.log \
             --error-logfile logs/error.log \
             app:app
else
    echo "Starting in development mode..."
    python app.py
fi
