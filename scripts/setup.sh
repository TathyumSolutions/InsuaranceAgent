#!/bin/bash
# Setup script for Standalone Insurance Voice Agent

set -e

echo "=========================================="
echo "Insurance Voice Agent - Setup"
echo "=========================================="

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

echo "✓ Dependencies installed"

# Create .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your OPENAI_API_KEY!"
else
    echo "✓ .env file already exists"
fi

# Create logs directory
mkdir -p logs
echo "✓ Logs directory created"

echo ""
echo "=========================================="
echo "✅ Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env file with your configuration:"
echo "   - OPENAI_API_KEY (required)"
echo "   - YOUR_DOMAIN (for production)"
echo ""
echo "2. Start the server:"
echo "   python app.py"
echo "   # or"
echo "   ./scripts/start.sh"
echo ""
echo "3. For local testing with voice calls:"
echo "   - Run: ngrok http 5000"
echo "   - Update YOUR_DOMAIN in .env with ngrok URL"
echo "   - Configure Twilio webhook"
echo ""
echo "4. Test without voice:"
echo "   curl http://localhost:5000/health"
echo ""
echo "=========================================="
