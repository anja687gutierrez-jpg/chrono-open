"""
Session Parser for Claude Code - FIXED VERSION
"""

import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Generator
import re

@dataclass
class SessionChunk:
    session_id: str
    project: str
    chunk_index: int
    content: str
    metadata: dict = field(default_factory=dict)

@dataclass
class SessionInfo:
    session_id: str
    project: str
    path: Path
    message_count: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    preview: str = ""

def extract_text_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type", "")
                if item_type == "text":
                    text = item.get("text", "")
                    if text:
                        texts.append(text)
                elif item_type == "thinking":
                    thinking = item.get("thinking", "")
                    if thinking and len(thinking) > 50:
                        texts.append(f"[Thinking: {thinking[:200]}...]")
                elif item_type == "tool_use":
                    name = item.get("name", "unknown")
                    texts.append(f"[Tool: {name}]")
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts)
    return str(content)

def extract_project_name(path: Path) -> str:
    project_dir = path.parent.name
    parts = project_dir.split("-")
    skip_words = {"Users", "anjacarrillo", "Desktop", "Documents", "Projects", "Claude", "Code", "Library", "CloudStorage", "GoogleDrive"}
    project_parts = [p for p in parts if p and p not in skip_words]
    if project_parts:
        return "-".join(project_parts[-3:]) if len(project_parts) > 3 else "-".join(project_parts)
    return project_dir[:30] if project_dir else "unknown"

def parse_jsonl_file(path: Path) -> Generator[dict, None, None]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Error reading {path}: {e}")

def get_message_text(msg: dict) -> tuple:
    msg_type = msg.get("type", "")
    if msg_type in ("user", "assistant"):
        message_obj = msg.get("message", {})
        role = message_obj.get("role", msg_type)
        content = message_obj.get("content", "")
        text = extract_text_content(content)
        return role, text
    if "role" in msg:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        text = extract_text_content(content)
        return role, text
    return "", ""

def chunk_session(path: Path, max_chunk_chars: int = 5000, max_messages: int = 500) -> List[SessionChunk]:
    session_id = path.stem
    project = extract_project_name(path)

    # Size-aware: limit messages for large files to prevent OOM
    try:
        file_size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        file_size_mb = 0

    if file_size_mb > 200:
        max_messages = min(max_messages, 200)
        print(f"    ⚠ Large session ({file_size_mb:.0f}MB), indexing first {max_messages} messages")
    elif file_size_mb > 100:
        max_messages = min(max_messages, 300)
        print(f"    ⚠ Large session ({file_size_mb:.0f}MB), indexing first {max_messages} messages")

    # Collect messages up to the limit instead of loading all at once
    messages = []
    for msg in parse_jsonl_file(path):
        messages.append(msg)
        if len(messages) >= max_messages:
            break

    if not messages:
        return []
    chunks = []
    current_chunk_parts = []
    current_chunk_size = 0
    chunk_index = 0
    first_timestamp = None
    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type in ("file-history-snapshot", "summary"):
            continue
        timestamp = msg.get("timestamp")
        role, text = get_message_text(msg)
        if not text or not text.strip():
            continue
        text = text.strip()
        if len(text) < 10:
            continue
        if first_timestamp is None and timestamp:
            first_timestamp = timestamp
        role_label = role.upper() if role else "UNKNOWN"
        formatted = f"{role_label}: {text}"
        if len(formatted) > max_chunk_chars:
            formatted = formatted[:max_chunk_chars - 50] + "... [truncated]"
        formatted_size = len(formatted)
        if current_chunk_size + formatted_size > max_chunk_chars and current_chunk_parts:
            chunk_text = "\n\n".join(current_chunk_parts)
            chunks.append(SessionChunk(session_id=session_id, project=project, chunk_index=chunk_index, content=chunk_text, metadata={"timestamp": first_timestamp, "preview": chunk_text[:200], "char_count": len(chunk_text)}))
            chunk_index += 1
            current_chunk_parts = []
            current_chunk_size = 0
            first_timestamp = timestamp
        current_chunk_parts.append(formatted)
        current_chunk_size += formatted_size
    if current_chunk_parts:
        chunk_text = "\n\n".join(current_chunk_parts)
        chunks.append(SessionChunk(session_id=session_id, project=project, chunk_index=chunk_index, content=chunk_text, metadata={"timestamp": first_timestamp, "preview": chunk_text[:200], "char_count": len(chunk_text)}))
    return chunks

def get_session_info(path: Path) -> Optional[SessionInfo]:
    session_id = path.stem
    project = extract_project_name(path)
    messages = list(parse_jsonl_file(path))
    if not messages:
        return None
    timestamps = []
    user_messages = []
    for msg in messages:
        if ts := msg.get("timestamp"):
            timestamps.append(ts)
        role, text = get_message_text(msg)
        if role == "user" and text:
            user_messages.append(text)
    preview = user_messages[0][:200] if user_messages else ""
    all_text = " ".join(user_messages)
    topics = extract_topics(all_text)
    return SessionInfo(session_id=session_id, project=project, path=path, message_count=len(messages), first_timestamp=timestamps[0] if timestamps else None, last_timestamp=timestamps[-1] if timestamps else None, topics=topics[:5], preview=preview)

def extract_topics(text: str) -> List[str]:
    patterns = [r'\b(React|Vue|Angular|TypeScript|JavaScript|Python|Node)\b', r'\b(API|REST|GraphQL|Firebase|Supabase|database)\b', r'\b(MagnusView|magnus|STAP|portal|dashboard)\b', r'\b(Tesla|rental|booking|tour)\b']
    topics = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for m in matches:
            if isinstance(m, str):
                topics.add(m.lower())
            elif isinstance(m, tuple):
                topics.add(m[0].lower())
    return list(topics)

def find_all_sessions(claude_dir: Path = None) -> List[Path]:
    if claude_dir is None:
        claude_dir = Path.home() / ".claude"
    sessions = []
    projects_dir = claude_dir / "projects"
    if projects_dir.exists():
        for jsonl_file in projects_dir.glob("**/*.jsonl"):
            if not jsonl_file.name.startswith("agent-"):
                sessions.append(jsonl_file)
    return sessions

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
        if test_path.exists():
            print(f"\nTesting parser on: {test_path.name}")
            print("=" * 60)
            messages = list(parse_jsonl_file(test_path))
            print(f"Total JSON lines: {len(messages)}")
            user_count = 0
            assistant_count = 0
            for msg in messages:
                role, text = get_message_text(msg)
                if role == "user":
                    user_count += 1
                elif role == "assistant":
                    assistant_count += 1
            print(f"User messages: {user_count}")
            print(f"Assistant messages: {assistant_count}")
            chunks = chunk_session(test_path)
            print(f"\nChunks created: {len(chunks)}")
            for i, chunk in enumerate(chunks[:3]):
                print(f"\n--- Chunk {i+1} Preview ---")
                print(chunk.content[:500])
                print("...")
        else:
            print(f"File not found: {test_path}")
    else:
        claude_dir = Path.home() / ".claude"
        print("Session Parser - Discovery Mode")
        print("=" * 60)
        sessions = find_all_sessions(claude_dir)
        print(f"\nFound {len(sessions)} session files")
        for path in sessions[:10]:
            chunks = chunk_session(path)
            if chunks:
                print(f"\nFirst session with content: {path.stem[:20]}...")
                print(f"Chunks: {len(chunks)}")
                print(f"Preview: {chunks[0].content[:300]}...")
                break
