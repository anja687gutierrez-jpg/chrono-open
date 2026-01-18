#!/bin/bash
# Smart Forking Setup Script
# Run this to set up your semantic search system for Claude Code sessions

set -e

echo "=========================================="
echo "Smart Forking - Setup"
echo "=========================================="
echo ""

# Check for Homebrew (needed for Ollama on Mac)
if ! command -v brew &> /dev/null; then
    echo "⚠ Homebrew not found. Installing..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Install Ollama if not present
if ! command -v ollama &> /dev/null; then
    echo "📦 Installing Ollama..."
    brew install ollama
else
    echo "✓ Ollama already installed"
fi

# Check if Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo ""
    echo "⚠ Ollama is not running!"
    echo ""
    echo "Please start Ollama in a separate terminal:"
    echo "  ollama serve"
    echo ""
    echo "Then run this setup script again."
    exit 1
fi

echo "✓ Ollama is running"

# Pull embedding model
echo ""
echo "📦 Pulling nomic-embed-text model..."
ollama pull nomic-embed-text

# Create Python virtual environment
echo ""
echo "🐍 Setting up Python environment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Created virtual environment"
else
    echo "✓ Virtual environment exists"
fi

# Activate and install dependencies
source venv/bin/activate

echo "📦 Installing Python packages..."
pip install --upgrade pip > /dev/null
pip install chromadb ollama > /dev/null

echo "✓ Installed chromadb and ollama"

# Create config directory
mkdir -p ~/.smart-forking

# Test the setup
echo ""
echo "🧪 Testing setup..."
python -c "
import chromadb
import ollama
print('  ✓ chromadb imported')
print('  ✓ ollama imported')

# Test embedding
response = ollama.embed(model='nomic-embed-text', input='test')
dim = len(response['embeddings'][0])
print(f'  ✓ Embedding works ({dim} dimensions)')
"

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Index your Claude Code sessions:"
echo "   source venv/bin/activate"
echo "   python indexer.py"
echo ""
echo "2. Search for relevant sessions:"
echo "   python fork_detect.py \"your feature description\""
echo ""
echo "3. (Optional) Add alias to your shell config:"
echo '   alias fork="python ~/Projects/smart-forking/fork_detect.py"'
echo ""
