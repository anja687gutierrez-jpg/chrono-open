# Smart Forking for Claude Code

Semantic search over your Claude Code sessions. Find relevant past conversations to fork from when starting new features.

## What This Does

Instead of starting every Claude Code session from scratch, Smart Forking lets you:

1. **Search your history** - Find past sessions that discussed similar topics
2. **Fork with context** - Continue from a relevant session so Claude already knows your codebase
3. **Build on prior knowledge** - Don't re-explain things you've already discussed

## Quick Start

### 1. Setup (one time)

```bash
# Make setup script executable and run it
chmod +x setup.sh
./setup.sh
```

This will:
- Install Ollama (if needed)
- Pull the `nomic-embed-text` embedding model
- Create a Python virtual environment
- Install chromadb and ollama packages

### 2. Index Your Sessions

```bash
source venv/bin/activate
python indexer.py
```

This scans `~/.claude/projects/` and indexes all your session transcripts.

First run may take a few minutes depending on how many sessions you have.

### 3. Find Relevant Sessions

```bash
python fork_detect.py "add real-time token usage to dashboard"
```

Example output:

```
=================================================================
🔍 Fork Session
=================================================================

Which session would you like to fork for: "add real-time token usage..."?

› 1. #8402b1ed (Recommended)
     Real-time token usage dashboard updates - best semantic match
     Project: STAP-Operations-Portal | Score: 81%

› 2. #3a850835
     Token usage field registration issues
     Project: STAP-Operations-Portal | Score: 74%

› 3. #e6b158a2
     Live stats implementation - 17 stories completed
     Project: STAP-Operations-Portal | Score: 67%

  4. None - start fresh

=================================================================
Fork Commands (copy to new terminal):
=================================================================

  #1: claude --continue 8402b1ed-xxxx-xxxx-xxxx
  #2: claude --continue 3a850835-xxxx-xxxx-xxxx
  #3: claude --continue e6b158a2-xxxx-xxxx-xxxx

  #0: claude  (start fresh)
```

### 4. Fork the Session

Copy the fork command for your chosen session:

```bash
claude --continue 8402b1ed-xxxx-xxxx-xxxx
```

Now Claude has full context from that previous session!

## Commands

### Indexer

```bash
# Index all new sessions
python indexer.py

# Reindex everything from scratch
python indexer.py --reindex

# Show stats only
python indexer.py --stats

# Test with limited sessions
python indexer.py --limit 10
```

### Fork Detect

```bash
# Basic search
python fork_detect.py "your feature description"

# Limit results
python fork_detect.py --top 3 "authentication flow"

# Filter by project
python fork_detect.py --project STAP "PDF export"

# Interactive mode
python fork_detect.py -i "dashboard updates"

# JSON output (for scripting)
python fork_detect.py --json "API integration"
```

## How It Works

1. **Session Parser** - Reads your Claude Code JSONL transcripts and chunks them into embeddable pieces
2. **Embedding Service** - Uses Ollama + nomic-embed-text to convert text into 768-dimensional vectors
3. **Vector Store** - ChromaDB stores embeddings locally and enables fast similarity search
4. **Fork Detect** - Embeds your query, searches for similar session chunks, aggregates by session

## File Structure

```
~/.claude/
├── projects/
│   └── {project-path}/
│       └── *.jsonl          # Session transcripts (indexed)

~/.smart-forking/
├── chroma/                  # Vector database storage
├── indexed_sessions.json    # Tracks what's been indexed

~/Projects/smart-forking/    # This project
├── session_parser.py        # Parse JSONL sessions
├── embedding_service.py     # Ollama embeddings
├── vector_store.py          # ChromaDB storage
├── indexer.py              # Build the index
├── fork_detect.py          # Search CLI
├── setup.sh                # Setup script
└── README.md
```

## Tips

### Add a Shell Alias

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
alias fork="cd ~/Projects/smart-forking && source venv/bin/activate && python fork_detect.py"
```

Now you can just run:
```bash
fork "add user authentication"
```

### Keep Index Updated

Run the indexer periodically (or add to a cron job):

```bash
# Add to crontab for daily indexing
0 2 * * * cd ~/Projects/smart-forking && source venv/bin/activate && python indexer.py
```

### Project-Specific Searches

When working on a specific project, filter results:

```bash
fork --project "Tour-Route-Planner" "map integration"
fork --project "STAP" "PDF export"
```

## Requirements

- macOS (tested on Apple Silicon)
- Python 3.9+
- Ollama
- ~500MB disk space for the embedding model
- ~100MB+ for vector database (depends on session count)

## Troubleshooting

### "Ollama is not running"

Start Ollama in a separate terminal:
```bash
ollama serve
```

### "No sessions indexed yet"

Run the indexer first:
```bash
python indexer.py
```

### Slow indexing

First run indexes everything. Subsequent runs only index new sessions.
For 100+ sessions, initial indexing may take 5-10 minutes.

### Search results not relevant

- Try different search queries
- Make sure you've indexed recent sessions
- Check that your sessions have meaningful content (not just quick fixes)

## Future Enhancements

See the original plan for Phase 5: Automated Context Management
- Pre-compaction transcript export
- Sub-agent context recovery
- Automatic session resume
- VS Code file watcher integration

## Credits

Inspired by the Smart Forking system shared in the Claude Code community.
