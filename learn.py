#!/usr/bin/env python3
"""
Learn - Teach AI Agents New Skills from Web Documentation

Scrape documentation from the web, chunk it, embed it, and store it
in a semantic database (ChromaDB) for retrieval.

Usage:
    learn "topic"                  # Auto-search and learn from official docs
    learn "topic" --url <url>      # Learn from specific URL(s)
    learn list                     # Show all learned topics
    learn search "query"           # Search the knowledge base
    learn refresh <topic>          # Re-scrape from original sources
    learn forget <topic>           # Delete a topic

Storage:
    ~/.chrono/knowledge/           # ChromaDB vector store
    ~/.chrono/learned_topics.json  # Topic index with metadata
"""

import argparse
import json
import sys
import time
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup
import html2text

from chrono_config import get_data_dir, atomic_write_json, safe_load_json
from embedding_service import EmbeddingService


# ============================================================
# Constants
# ============================================================

KNOWLEDGE_DIR = get_data_dir() / "knowledge"
TOPICS_FILE = get_data_dir() / "learned_topics.json"
CHUNK_SIZE = 1000  # chars per chunk
CHUNK_OVERLAP = 100  # overlap between chunks
MAX_PAGES = 20  # max pages to follow per topic
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrono/2.0 LearnBot"


# ============================================================
# Data Classes
# ============================================================

@dataclass
class DocChunk:
    """A chunk of documentation text."""
    session_id: str  # topic name (reusing ChromaDB schema)
    project: str  # "knowledge"
    chunk_index: int
    content: str
    metadata: dict = field(default_factory=dict)


# ============================================================
# Web Scraping
# ============================================================

def fetch_page(url: str) -> Optional[str]:
    """Fetch a web page and return its HTML content."""
    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  Warning: Failed to fetch {url}: {e}")
        return None


def html_to_text(html_content: str) -> str:
    """Convert HTML to clean text using html2text."""
    # First remove script/style/nav elements
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
        tag.decompose()

    # Find main content area if possible
    main = soup.find("main") or soup.find("article") or soup.find(role="main")
    if main:
        html_str = str(main)
    else:
        body = soup.find("body")
        html_str = str(body) if body else str(soup)

    # Convert to markdown-ish text
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0  # no line wrapping
    converter.skip_internal_links = True

    text = converter.handle(html_str)

    # Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def extract_links(html_content: str, base_url: str) -> List[str]:
    """Extract internal links from HTML for following."""
    from urllib.parse import urljoin, urlparse

    soup = BeautifulSoup(html_content, "html.parser")
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc
    base_path = base_parsed.path.rstrip("/")

    links = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only follow same-domain links under the same path prefix
        if parsed.netloc == base_domain and parsed.path.startswith(base_path):
            # Remove fragments and query params for dedup
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean_url.rstrip("/") != base_url.rstrip("/"):
                links.add(clean_url)

    return list(links)[:MAX_PAGES]


def scrape_url(url: str, follow_links: bool = True) -> List[Dict[str, str]]:
    """
    Scrape a URL and optionally follow internal links.

    Returns list of {"url": ..., "text": ...} dicts.
    """
    pages = []
    visited = set()

    def _scrape(u: str, depth: int = 0):
        if u in visited or len(pages) >= MAX_PAGES:
            return
        visited.add(u)

        html = fetch_page(u)
        if not html:
            return

        text = html_to_text(html)
        if text and len(text) > 100:  # skip near-empty pages
            pages.append({"url": u, "text": text})
            print(f"  Scraped: {u} ({len(text)} chars)")

        # Follow links one level deep from the starting URL
        if follow_links and depth == 0 and len(pages) < MAX_PAGES:
            child_links = extract_links(html, u)
            for link in child_links:
                if len(pages) >= MAX_PAGES:
                    break
                _scrape(link, depth + 1)

    _scrape(url)
    return pages


# ============================================================
# Chunking
# ============================================================

def chunk_text(text: str, source_url: str, topic: str, start_idx: int = 0) -> List[DocChunk]:
    """Split text into overlapping chunks for embedding.

    Args:
        start_idx: Starting chunk index (to avoid ID collisions across pages)

    Returns:
        List of DocChunk objects
    """
    if not text or len(text) < 50:
        return []

    chunks = []
    # Split on paragraph boundaries first
    paragraphs = text.split("\n\n")

    current_chunk = ""
    chunk_idx = start_idx

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph would exceed chunk size, save current and start new
        if len(current_chunk) + len(para) + 2 > CHUNK_SIZE and current_chunk:
            chunks.append(DocChunk(
                session_id=topic,
                project="knowledge",
                chunk_index=chunk_idx,
                content=current_chunk.strip(),
                metadata={
                    "preview": current_chunk[:200],
                    "timestamp": datetime.now().isoformat(),
                    "source_url": source_url,
                    "topic": topic,
                    "char_count": len(current_chunk)
                }
            ))
            chunk_idx += 1

            # Keep overlap from end of current chunk
            if len(current_chunk) > CHUNK_OVERLAP:
                current_chunk = current_chunk[-CHUNK_OVERLAP:] + "\n\n" + para
            else:
                current_chunk = para
        else:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para

    # Don't forget the last chunk
    if current_chunk.strip():
        chunks.append(DocChunk(
            session_id=topic,
            project="knowledge",
            chunk_index=chunk_idx,
            content=current_chunk.strip(),
            metadata={
                "preview": current_chunk[:200],
                "timestamp": datetime.now().isoformat(),
                "source_url": source_url,
                "topic": topic,
                "char_count": len(current_chunk)
            }
        ))

    return chunks


# ============================================================
# ChromaDB Knowledge Store
# ============================================================

class KnowledgeStore:
    """ChromaDB-based store for learned documentation."""

    def __init__(self):
        self.persist_path = KNOWLEDGE_DIR
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None

    @property
    def client(self):
        if self._client is None:
            import chromadb
            from chromadb.config import Settings
            self._client = chromadb.PersistentClient(
                path=str(self.persist_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name="learned_knowledge",
                metadata={
                    "hnsw:space": "cosine",
                    "description": "Documentation scraped via learn command"
                }
            )
        return self._collection

    def add_chunks(self, chunks: List[DocChunk], embeddings: List[List[float]]) -> int:
        if not chunks or not embeddings:
            return 0

        valid = [(c, e) for c, e in zip(chunks, embeddings) if e and len(e) > 0]
        if not valid:
            return 0

        chunks, embeddings = zip(*valid)

        ids = [f"{c.session_id}_{c.chunk_index}" for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "session_id": c.session_id,
                "project": c.project,
                "chunk_index": c.chunk_index,
                "preview": c.metadata.get("preview", "")[:500],
                "timestamp": c.metadata.get("timestamp", ""),
                "source_url": c.metadata.get("source_url", ""),
                "topic": c.metadata.get("topic", ""),
                "char_count": c.metadata.get("char_count", 0)
            }
            for c in chunks
        ]

        self.collection.upsert(
            ids=list(ids),
            embeddings=list(embeddings),
            documents=list(documents),
            metadatas=list(metadatas)
        )

        return len(ids)

    def search(self, query_embedding: List[float], n_results: int = 10,
               topic_filter: Optional[str] = None) -> List[Dict]:
        where_filter = None
        if topic_filter:
            where_filter = {"topic": {"$eq": topic_filter}}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        search_results = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            score = max(0, min(100, int((1 - distance / 2) * 100)))
            metadata = results["metadatas"][0][i]
            document = results["documents"][0][i] if results.get("documents") else ""

            search_results.append({
                "topic": metadata.get("topic", ""),
                "source_url": metadata.get("source_url", ""),
                "score": score,
                "content": document[:800] if document else "",
                "preview": metadata.get("preview", "")[:200],
            })

        return search_results

    def delete_topic(self, topic: str) -> int:
        results = self.collection.get(
            where={"topic": {"$eq": topic}},
            include=[]
        )
        if results and results.get("ids"):
            self.collection.delete(ids=results["ids"])
            return len(results["ids"])
        return 0

    def count_topic(self, topic: str) -> int:
        results = self.collection.get(
            where={"topic": {"$eq": topic}},
            include=[]
        )
        return len(results.get("ids", []))

    def get_stats(self) -> Dict[str, Any]:
        count = self.collection.count()
        return {"total_chunks": count, "storage_path": str(self.persist_path)}


# ============================================================
# Topic Index
# ============================================================

def load_topics() -> Dict:
    data = safe_load_json(TOPICS_FILE, default={"topics": {}})
    if not isinstance(data, dict) or "topics" not in data:
        return {"topics": {}}
    return data


def save_topics(data: Dict):
    atomic_write_json(TOPICS_FILE, data)


def update_topic_entry(topic: str, chunk_count: int, sources: List[str]):
    data = load_topics()
    now = datetime.now().isoformat()
    if topic in data["topics"]:
        data["topics"][topic]["chunk_count"] = chunk_count
        data["topics"][topic]["sources"] = sources
        data["topics"][topic]["last_refreshed"] = now
    else:
        data["topics"][topic] = {
            "chunk_count": chunk_count,
            "sources": sources,
            "indexed_at": now,
            "last_refreshed": now
        }
    save_topics(data)


def remove_topic_entry(topic: str):
    data = load_topics()
    if topic in data["topics"]:
        del data["topics"][topic]
        save_topics(data)


# ============================================================
# Commands
# ============================================================

def cmd_learn(topic: str, urls: List[str], follow: bool = True):
    """Learn a topic from one or more URLs."""
    print(f"\n  Learning: {topic}")
    print(f"  URLs: {len(urls)}")

    # 1. Scrape all URLs
    all_pages = []
    for url in urls:
        print(f"\n  Scraping {url}...")
        pages = scrape_url(url, follow_links=follow)
        all_pages.extend(pages)

    if not all_pages:
        print(f"\n  Error: No content scraped from any URL.")
        return

    print(f"\n  Total pages scraped: {len(all_pages)}")

    # 2. Chunk all content (use running index to avoid ID collisions)
    all_chunks = []
    running_idx = 0
    for page in all_pages:
        chunks = chunk_text(page["text"], page["url"], topic, start_idx=running_idx)
        all_chunks.extend(chunks)
        running_idx += len(chunks)

    if not all_chunks:
        print(f"  Error: No chunks created (content too short?).")
        return

    print(f"  Total chunks: {len(all_chunks)}")

    # 3. Embed chunks
    print(f"  Embedding {len(all_chunks)} chunks...")
    embedder = EmbeddingService()

    if not embedder.check_model_available():
        print("  Error: Ollama model not available. Start Ollama first:")
        print("    ollama serve")
        return

    # Truncate any chunks that are too long for the embedding model (8192 tokens ~ 24K chars)
    MAX_EMBED_CHARS = 24000
    texts = [c.content[:MAX_EMBED_CHARS] for c in all_chunks]
    embeddings = embedder.embed_batch(texts, batch_size=10, show_progress=True)

    # 4. Store in ChromaDB
    print(f"  Storing in knowledge base...")
    store = KnowledgeStore()

    # Delete old chunks for this topic first (for refresh)
    old_count = store.delete_topic(topic)
    if old_count > 0:
        print(f"  Replaced {old_count} existing chunks")

    added = store.add_chunks(all_chunks, embeddings)
    print(f"  Indexed {added} chunks")

    # 5. Update topic index
    source_urls = list(set(p["url"] for p in all_pages))
    update_topic_entry(topic, added, source_urls)

    # Report
    print(f"\n  {'='*40}")
    print(f"  Learned: {topic}")
    print(f"  Pages: {len(all_pages)} scraped")
    print(f"  Chunks: {added} indexed")
    print(f"  Sources:")
    for u in source_urls[:10]:
        print(f"    - {u}")
    if len(source_urls) > 10:
        print(f"    ... and {len(source_urls) - 10} more")
    print()


def cmd_list():
    """List all learned topics."""
    data = load_topics()
    topics = data.get("topics", {})

    if not topics:
        print("\n  No topics learned yet.")
        print("  Use: learn \"topic\" --url <url>\n")
        return

    print(f"\n  {'='*60}")
    print(f"  LEARNED TOPICS ({len(topics)} total)")
    print(f"  {'='*60}")
    print(f"  {'Topic':<30} {'Chunks':>8} {'Sources':>8}  {'Indexed'}")
    print(f"  {'-'*30} {'-'*8} {'-'*8}  {'-'*19}")

    total_chunks = 0
    for name, info in sorted(topics.items()):
        chunks = info.get("chunk_count", 0)
        sources = len(info.get("sources", []))
        indexed = info.get("indexed_at", "")[:10]
        total_chunks += chunks
        print(f"  {name:<30} {chunks:>8} {sources:>8}  {indexed}")

    print(f"  {'-'*30} {'-'*8}")
    print(f"  {'Total':<30} {total_chunks:>8}")
    print()


def cmd_search(query: str, n_results: int = 5):
    """Search the knowledge base."""
    print(f"\n  Searching: \"{query}\"")

    embedder = EmbeddingService()
    if not embedder.check_model_available():
        print("  Error: Ollama not available. Run: ollama serve")
        return

    query_embedding = embedder.embed(query)

    store = KnowledgeStore()
    results = store.search(query_embedding, n_results=n_results)

    if not results:
        print("  No results found.\n")
        return

    print(f"\n  {'='*60}")
    print(f"  Knowledge Search: \"{query}\"")
    print(f"  {'='*60}")

    for i, r in enumerate(results, 1):
        print(f"\n  Result {i} (from {r['topic']}) — {r['score']}% match")
        print(f"  {'-'*50}")
        # Show first 300 chars of content
        content = r["content"][:300].strip()
        for line in content.split("\n"):
            print(f"  {line}")
        print(f"  Source: {r['source_url']}")

    print(f"\n  {len(results)} results from learned knowledge.\n")


def cmd_refresh(topic: str):
    """Re-scrape and re-index a topic from its original sources."""
    data = load_topics()
    if topic not in data.get("topics", {}):
        print(f"\n  Error: Topic '{topic}' not found.")
        print(f"  Use 'learn list' to see available topics.\n")
        return

    sources = data["topics"][topic].get("sources", [])
    if not sources:
        print(f"\n  Error: No sources recorded for '{topic}'.\n")
        return

    print(f"\n  Refreshing '{topic}' from {len(sources)} sources...")
    cmd_learn(topic, sources, follow=False)


def cmd_forget(topic: str):
    """Delete a topic from the knowledge base."""
    store = KnowledgeStore()
    deleted = store.delete_topic(topic)
    remove_topic_entry(topic)

    if deleted > 0:
        print(f"\n  Forgot '{topic}' ({deleted} chunks removed).\n")
    else:
        print(f"\n  Topic '{topic}' not found in knowledge base.\n")


# ============================================================
# Main CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Learn - Teach AI agents from web documentation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  learn "nextjs-routing" --url https://nextjs.org/docs/routing
  learn list
  learn search "how to create API routes"
  learn refresh nextjs-routing
  learn forget nextjs-routing
        """
    )

    parser.add_argument(
        "command",
        help="Topic name, 'list', 'search', 'refresh', or 'forget'"
    )

    parser.add_argument(
        "args",
        nargs="*",
        help="Additional arguments (search query, etc.)"
    )

    parser.add_argument(
        "--url", "-u",
        action="append",
        default=[],
        help="URL(s) to scrape (can specify multiple)"
    )

    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="Don't follow internal links"
    )

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "search":
        query = " ".join(args.args) if args.args else ""
        if not query:
            print("\n  Error: Please provide a search query.")
            print("  Usage: learn search \"your query\"\n")
            return
        cmd_search(query)
    elif args.command == "refresh":
        topic = args.args[0] if args.args else ""
        if not topic:
            print("\n  Error: Please specify a topic to refresh.\n")
            return
        cmd_refresh(topic)
    elif args.command == "forget":
        topic = args.args[0] if args.args else ""
        if not topic:
            print("\n  Error: Please specify a topic to forget.\n")
            return
        cmd_forget(topic)
    else:
        # It's a topic name — learn it
        topic = args.command
        urls = args.url

        if not urls:
            print(f"\n  Error: Please provide at least one --url.")
            print(f"  Usage: learn \"{topic}\" --url <url>\n")
            return

        cmd_learn(topic, urls, follow=not args.no_follow)


if __name__ == "__main__":
    main()
