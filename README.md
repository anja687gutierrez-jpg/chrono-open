# Smart Forking for Claude Code

Semantic search over your Claude Code sessions. Find relevant past conversations to fork from when starting new features.

---

## Project Epoch - Chrono Trigger Time Machine

**NEW!** Enhanced with Chrono Trigger-inspired time travel mechanics:

```bash
chrono "firebase authentication"           # Search all eras
chrono "dashboard" --era future            # This week only
chrono "API" --since "3 months ago"        # Date range filter
chrono eras                                # Show all time periods
```

### Time Eras

Sessions are automatically classified into Chrono Trigger-inspired eras:

| Era | Game Year | Time Period |
|-----|-----------|-------------|
| Prehistory | 65M BC | Sessions older than 6 months |
| Antiquity | 12000 BC | Sessions 3-6 months old |
| Middle Ages | 600 AD | Sessions 1-3 months old |
| Present | 1000 AD | Sessions from last month |
| Future | 2300 AD | Sessions from this week |

### Date Range Filtering

Flexible date parsing supports multiple formats:

```bash
chrono "query" --since 2024-06-15 --until 2025-12-31   # Absolute dates
chrono "query" --since "3 months ago"                   # Relative dates
chrono "query" --since "last week"                      # Natural language
chrono "query" --era present --project magnusview       # Combined filters
```

---

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

### Chrono (Project Epoch - Recommended)

```bash
# Search across all eras
chrono "your feature description"

# View all time eras with session counts
chrono eras

# Filter by era
chrono "dashboard" --era future          # This week
chrono "auth" --era present              # Last month
chrono "API" --era middle_ages           # 1-3 months ago

# Date range filtering (flexible formats)
chrono "react" --since "3 months ago"
chrono "firebase" --since 2024-01 --until 2025-06
chrono "query" --since "last week" --until "yesterday"

# Combined filters
chrono "dashboard" --era present --project magnusview -n 10

# Sort by date instead of relevance
chrono "query" --sort date

# JSON output (for scripting)
chrono "query" --json

# Interactive mode
chrono "query" -i
```

### Indexer

```bash
# Index all new sessions
chrono index

# Reindex everything from scratch
chrono index --reindex

# Index a single session by ID (supports short IDs)
chrono index 4717c89a

# Remove stale entries (sessions deleted from disk but still in ChromaDB)
chrono cleanup

# Show stats only
python indexer.py --stats

# Test with limited sessions
python indexer.py --limit 10
```

**Size-Aware Indexing:** Sessions larger than 100MB are automatically truncated (first 300 messages for 100-200MB, first 200 for >200MB) to prevent out-of-memory crashes.

**Hybrid Search:** Search now combines semantic (vector) results with full-text matching. Queries like `chrono "detailModal.js"` will find exact string matches even when embeddings don't capture them.

### Fork Detect (Original - Still Works)

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
├── gates.json               # Time Gates bookmarks (Phase 2)

~/Desktop/smart-forking/     # This project
├── chrono.py               # Era-based session search
├── chrono_utils.py         # Time utilities & era classification
├── gates.py                # Time Gates (session bookmarking)
├── epoch.py                # Git time machine
├── techs.py                # Workflow automation
├── lavos.py                # Project health monitoring
├── session_parser.py        # Parse JSONL sessions
├── embedding_service.py     # Ollama embeddings
├── vector_store.py          # ChromaDB storage
├── indexer.py              # Build the index
├── fork_detect.py          # Original search CLI
└── README.md
```

## Tips

### Shell Aliases

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
# Original Smart Forking
alias fork="cd ~/Desktop/smart-forking && source venv/bin/activate && python fork_detect.py"
alias fork-latest="cd ~/Desktop/smart-forking && source venv/bin/activate && python fork_detect.py --sort date"

# Project Epoch - Chrono Trigger Time Machine
alias chrono="cd ~/Desktop/smart-forking && source venv/bin/activate && python chrono.py"
alias chrono-eras="cd ~/Desktop/smart-forking && source venv/bin/activate && python chrono.py eras"
alias epoch="chrono"  # Alternate name

# Time Gates - Session Bookmarking
alias gate="cd ~/Desktop/smart-forking && source venv/bin/activate && python gates.py"

# Epoch - Git Time Machine
alias egit="cd ~/Desktop/smart-forking && source venv/bin/activate && python epoch.py"

# Techs - Workflow Automation
alias tech="cd ~/Desktop/smart-forking && source venv/bin/activate && python techs.py"

# Lavos Detection - Project Health Monitoring
alias lavos="source ~/Desktop/smart-forking/venv/bin/activate && python ~/Desktop/smart-forking/lavos.py"
```

Now you can just run:
```bash
chrono "add user authentication"        # Enhanced time-travel search
chrono-eras                             # View all time periods
gate save my-project                    # Bookmark a session
gate list                               # View End of Time (all bookmarks)
gate jump my-project                    # Get continue command
egit                                    # Git status with era info
egit log                                # Commit history by era
egit timeline                           # Visual git graph
tech list                               # Show all workflow techs
tech fire                               # Build project
tech antipode                           # Build + Test (Dual Tech)
tech luminaire                          # Build + Test + Deploy (Triple Tech!)
lavos                                   # Full project health scan
lavos quick                             # Critical issues only
fork "add user authentication"          # Original search (still works)
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

- Try different search queries (exact file names and identifiers now work via full-text fallback)
- Make sure you've indexed recent sessions
- Check that your sessions have meaningful content (not just quick fixes)
- Run `chrono cleanup` to remove stale entries from deleted sessions

### Large sessions crashing the indexer

Sessions >100MB are automatically truncated during indexing. If a session still causes a MemoryError, it will be skipped gracefully. You can re-index a single session with:

```bash
chrono index <session-id>
```

## Time Gates - Session Bookmarking (Phase 2 ✅)

In Chrono Trigger, Time Gates are portals connecting different eras. The "End of Time" is a hub where you can access any time period. In Project Epoch, Time Gates let you bookmark important sessions for instant access.

### Quick Commands

```bash
gate save my-project                    # Bookmark most recent session
gate save auth-work abc12345            # Bookmark specific session
gate save dashboard --notes "WIP on v2" # Add notes
gate list                               # Show all gates (End of Time)
gate jump my-project                    # Get continue command
gate info my-project                    # Detailed gate info
gate rename old-name new-name           # Rename a gate
gate delete my-project                  # Remove bookmark
```

### Example Workflow

```bash
# After a productive session on auth...
gate save auth-flow --notes "OAuth setup complete"

# Later, when you need to continue...
gate list                    # See all your bookmarks
gate jump auth-flow          # Get the continue command
# Output: claude --continue abc12345-...
```

---

## Epoch - Git Time Machine (Phase 3 ✅)

In Chrono Trigger, the Epoch (Wings of Time) allows free travel to any point in history. In Project Epoch, it provides Chrono-themed git navigation.

### Quick Commands

```bash
egit                          # Status - where am I in the timeline?
egit log                      # Commit history grouped by era
egit log -n 20                # Show more commits
egit branches                 # All branches organized by era
egit timeline                 # ASCII visual history
egit jump feature-branch      # Switch branch
egit jump abc123 -b fix-bug   # Create branch at commit
egit compare main..feature    # Compare branches
egit stash save "WIP"         # Stash changes
egit stash pop                # Restore stashed changes
```

### Example Output

```
🚀 EPOCH STATUS - Current Position in Timeline
═══════════════════════════════════════════════════════
Repository:  my-project
Branch:      feature-auth
Commit:      abc1234
Era:         🏠 This Week (2 days ago)
Changes:     +3 staged ~5 unstaged
```

---

## Techs - Workflow Automation (Phase 4 ✅)

In Chrono Trigger, Techs are special abilities that characters can combine for powerful attacks. In Project Epoch, Techs are command combos for development workflows!

### Quick Commands

```bash
tech list                              # Show all available techs
tech fire                              # Build (Lucca's fire)
tech ice                               # Test (Marle's ice)
tech slash                             # Lint (Crono's slash)
tech cure                              # Auto-fix issues
tech antipode                          # Build + Test (Dual Tech)
tech luminaire                         # Build + Test + Deploy (Triple Tech!)
tech fire --dry-run                    # Preview without executing
tech custom my-flow "npm run build"    # Create custom tech
```

### Tech Categories

| Type | Example | Description |
|------|---------|-------------|
| **Single** | `tech fire` | Individual commands (build, test, lint) |
| **Dual** | `tech antipode` | Two-step combos (build + test) |
| **Triple** | `tech luminaire` | Full workflows (build + test + deploy) |
| **Custom** | `tech my-flow` | Your own command chains |

### Popular Techs

| Tech | Element | Characters | Action |
|------|---------|------------|--------|
| `fire` | 🔥 | Lucca | Build project |
| `ice` | ❄️ | Marle | Run tests |
| `slash` | ⚡ | Crono | Lint code |
| `cure` | 💚 | Marle | Auto-fix issues |
| `antipode` | 🔥❄️ | Lucca+Marle | Build + Test |
| `luminaire` | ⭐ | All | Build + Test + Deploy |

---

## Lavos Detection - Project Health (Phase 5 ✅)

In Chrono Trigger, Lavos is a parasitic alien that has been dormant for 65 million years, waiting to destroy the world. In Project Epoch, Lavos Detection finds the "dormant threats" in your codebase - problems that will cause damage if not addressed!

### Quick Commands

```bash
lavos                    # Full project scan
lavos quick              # Critical issues only (faster)
lavos security           # Security-focused scan
lavos deps               # Dependency health check
lavos scan --report      # Generate JSON report
```

### Threat Levels

| Level | Meaning |
|-------|---------|
| 🔴 **CRITICAL** | Day of Lavos imminent! Fix immediately |
| 🟠 **HIGH** | Lavos stirs beneath the surface |
| 🟡 **MEDIUM** | Minor disturbances detected |
| 🔵 **LOW** | Timeline relatively stable |

### What It Detects

| Category | Examples |
|----------|----------|
| 🔒 **Security** | npm audit vulnerabilities, exposed secrets |
| 📦 **Dependencies** | Outdated packages, deprecated APIs |
| ✨ **Quality** | Linting errors, TODO/FIXME markers |
| ⚙️ **Config** | .env not in .gitignore, sensitive files |
| 📂 **Git** | Large files, untracked source files |

---

## Future Enhancements (Project Epoch Roadmap)

### Phase 6: Skill Registration - Final Phase!
- Register as Claude Code skill
- `/chrono` slash command
- MCP integration

---

See the original plan for Smart Forking Phase 5: Automated Context Management
- Pre-compaction transcript export
- Sub-agent context recovery
- Automatic session resume

## Credits

Inspired by the Smart Forking system shared in the Claude Code community.
Enhanced with Chrono Trigger-inspired time mechanics (Project Epoch).
