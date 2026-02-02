# Smart Forking for Claude Code

A semantic search system that finds relevant past Claude Code sessions so you can fork from them with full context. Never lose valuable project knowledge between sessions again.

---

## What It Does

When you want to work on a feature, Smart Forking searches through all your past Claude Code sessions and finds the most relevant ones. You can then "fork" from that session, starting a new Claude Code instance with all that previous context already loaded.

**Example:**
```bash
python fork_detect.py "magnusview dashboard"

# Results:
# 1. #bf695425 (77%) - "Done! MagnusView is ready..."
# 2. #6f3b5da0 (72%) - "Now add the fallback component..."
# 3. #c87186ec (69%) - "The DigestModal is being rendered..."

# Then fork from the best match:
claude --continue bf695425-407f-4bcd-b1d2-6d2277f59399
```

---

## Installation

### Prerequisites

- macOS with Homebrew
- Python 3.9+
- Claude Code CLI installed

### Step 1: Install Ollama (Local Embedding Model)

```bash
brew install ollama
brew services start ollama
ollama pull nomic-embed-text
```

### Step 2: Set Up the Project

```bash
cd ~/Desktop/smart-forking
python3 -m venv venv
source venv/bin/activate
pip install chromadb ollama
```

### Step 3: Index Your Sessions

```bash
python indexer.py
```

This will scan all your Claude Code sessions in `~/.claude/projects/` and create searchable embeddings.

---

## Usage

### Finding Relevant Sessions

```bash
cd ~/Desktop/smart-forking
source venv/bin/activate
python fork_detect.py "your search query"
```

**Search examples:**
```bash
python fork_detect.py "magnusview"
python fork_detect.py "Tesla rental website"
python fork_detect.py "Firebase authentication"
python fork_detect.py "PDF export feature"
python fork_detect.py "React TypeScript dashboard"
```

### Forking a Session

After running `fork_detect.py`, copy the fork command for your chosen session:

```bash
# In a NEW terminal window:
claude --continue bf695425-407f-4bcd-b1d2-6d2277f59399
```

This starts Claude Code with all the context from that previous session.

### Updating the Index

After working on projects, add your new sessions to the database:

```bash
cd ~/Desktop/smart-forking
source venv/bin/activate
python indexer.py
```

To completely rebuild the index:
```bash
python indexer.py --reindex
```

---

## Quick Access Shortcut

Add this alias to your `~/.zshrc`:

```bash
echo 'alias fork="cd ~/Desktop/smart-forking && source venv/bin/activate && python fork_detect.py"' >> ~/.zshrc
source ~/.zshrc
```

Now you can simply run:
```bash
fork "magnusview dashboard"
fork "Tesla booking"
```

---

## Project Structure

```
~/Desktop/smart-forking/
├── session_parser.py    # Parses Claude Code JSONL session files
├── embedding_service.py # Connects to Ollama for embeddings
├── vector_store.py      # ChromaDB vector database wrapper
├── indexer.py           # Indexes all sessions into the database
├── fork_detect.py       # CLI tool to search and fork sessions
├── venv/                # Python virtual environment
└── README.md            # This file

~/.smart-forking/
└── chroma/              # Vector database storage
```

---

## Google Drive Backup (For Multiple Laptops)

### Move Project to Google Drive

```bash
# Move the project
mv ~/Desktop/smart-forking "/Users/anjacarrillo/Library/CloudStorage/GoogleDrive-anja687gutierrez@gmail.com/My Drive/Business/Apps/smart-forking"

# Create Desktop symlink for easy access
ln -s "/Users/anjacarrillo/Library/CloudStorage/GoogleDrive-anja687gutierrez@gmail.com/My Drive/Business/Apps/smart-forking" ~/Desktop/smart-forking
```

### Backup the Vector Database

```bash
# Move database to Google Drive
mv ~/.smart-forking "/Users/anjacarrillo/Library/CloudStorage/GoogleDrive-anja687gutierrez@gmail.com/My Drive/Business/Apps/smart-forking-data"

# Create symlink
ln -s "/Users/anjacarrillo/Library/CloudStorage/GoogleDrive-anja687gutierrez@gmail.com/My Drive/Business/Apps/smart-forking-data" ~/.smart-forking
```

### Setting Up on a New Laptop

1. **Install Ollama:**
   ```bash
   brew install ollama
   brew services start ollama
   ollama pull nomic-embed-text
   ```

2. **Navigate to Google Drive folder:**
   ```bash
   cd "/path/to/Google Drive/Business/Apps/smart-forking"
   ```

3. **Recreate virtual environment (if needed):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install chromadb ollama
   ```

4. **Create symlink for database:**
   ```bash
   ln -s "/path/to/Google Drive/Business/Apps/smart-forking-data" ~/.smart-forking
   ```

5. **Test it:**
   ```bash
   python fork_detect.py "test"
   ```

**Note:** Claude Code sessions (`~/.claude/projects/`) are local to each machine. You can either:
- Copy `~/.claude/projects/` to the new machine
- Start fresh and build new indexed sessions on the new machine

---

## Workflow Summary

| Situation | Command |
|-----------|---------|
| Find relevant past work | `fork "your feature"` |
| Continue from a found session | `claude --continue <session-id>` |
| Resume today's last session | `claude --resume` |
| Update index after work | `python indexer.py` |
| Full reindex | `python indexer.py --reindex` |

---

## Troubleshooting

### "Model not found" error
```bash
ollama pull nomic-embed-text
```

### "No content to index" for most sessions
The session parser might not be handling the format. Test with:
```bash
python session_parser.py ~/.claude/projects/-Users-anjacarrillo/<session-id>.jsonl
```

### Slow indexing
Large sessions take time. The first full index of ~50 sessions takes about 5 minutes.

### Can't find recent sessions
Run `python indexer.py` to add new sessions to the database.

---

## How It Works

1. **Session Parser** reads Claude Code's JSONL session files and extracts conversation content
2. **Embedding Service** uses Ollama's `nomic-embed-text` model to convert text into 768-dimensional vectors
3. **Vector Store** (ChromaDB) stores these embeddings for fast similarity search
4. **Fork Detect** embeds your query and finds the most similar session chunks
5. **Claude --continue** loads that session's context into a new Claude Code instance

---

## Stats

After indexing:
- **Sessions indexed:** 27
- **Chunks in database:** 576
- **Search time:** <1 second

---

## Credits

Inspired by the Claude Code community's context management techniques, particularly the "Ralph workflow" and automated session handoff systems.

---

*Last updated: January 2026*