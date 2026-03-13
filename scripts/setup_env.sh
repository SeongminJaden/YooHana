#!/usr/bin/env bash
# AI Influencer - Environment Setup Script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== AI Influencer Environment Setup ==="
echo "Project directory: $PROJECT_DIR"

# Check Python version
python3 --version || { echo "ERROR: Python 3 not found"; exit 1; }

# Check CUDA
if command -v nvidia-smi &> /dev/null; then
    echo "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "WARNING: No GPU detected. Training will be very slow."
fi

# Install runtime dependencies
echo ""
echo "=== Installing runtime dependencies ==="
pip install -r "$PROJECT_DIR/requirements.txt"

# Ask about training dependencies
read -p "Install training dependencies (unsloth, peft, trl, wandb)? [y/N]: " install_train
if [[ "${install_train,,}" == "y" ]]; then
    echo "=== Installing training dependencies ==="
    pip install -r "$PROJECT_DIR/requirements-train.txt"
fi

# Create .env if it doesn't exist
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo ""
    echo "Created .env file from .env.example"
    echo "Please edit .env and fill in your API keys."
fi

# Create output directories
mkdir -p "$PROJECT_DIR/outputs/images"
mkdir -p "$PROJECT_DIR/outputs/logs"
mkdir -p "$PROJECT_DIR/data/raw"
mkdir -p "$PROJECT_DIR/data/processed"
mkdir -p "$PROJECT_DIR/data/reference_images"
mkdir -p "$PROJECT_DIR/data/training"
mkdir -p "$PROJECT_DIR/models/base"
mkdir -p "$PROJECT_DIR/models/adapter"
mkdir -p "$PROJECT_DIR/models/merged"

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: python scripts/collect_data.py   (data collection)"
echo "  3. Run: python scripts/train.py          (fine-tuning)"
echo "  4. Run: python scripts/run_bot.py        (start the bot)"
