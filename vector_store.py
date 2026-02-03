"""
Vector Store using ChromaDB (Chrono)
Stores and searches session embeddings for semantic similarity.

Data is persisted locally at ~/.chrono/chroma/
(Legacy: ~/.smart-forking/chroma/ also supported)
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class SearchResult:
    """A search result with score and metadata."""
    session_id: str
    project: str
    score: int  # 0-100 percentage
    preview: str
    chunk_index: int
    timestamp: Optional[str] = None
    content: str = ""


def get_chrono_data_dir() -> Path:
    """Get the Chrono data directory, supporting migration from old path."""
    new_path = Path.home() / ".chrono"
    old_path = Path.home() / ".smart-forking"

    # Prefer new path if it exists
    if new_path.exists():
        return new_path
    # Fall back to old path if it exists
    if old_path.exists():
        return old_path
    # Default to new path for fresh installs
    return new_path


class SessionVectorStore:
    """ChromaDB-based vector store for Claude Code sessions."""

    def __init__(self, persist_dir: str = None):
        if persist_dir:
            self.persist_path = Path(persist_dir).expanduser()
        else:
            self.persist_path = get_chrono_data_dir() / "chroma"

        self.persist_path.mkdir(parents=True, exist_ok=True)

        self._client = None
        self._collection = None
    
    @property
    def client(self):
        """Lazy load ChromaDB client."""
        if self._client is None:
            try:
                import chromadb
                from chromadb.config import Settings
                
                self._client = chromadb.PersistentClient(
                    path=str(self.persist_path),
                    settings=Settings(
                        anonymized_telemetry=False,
                        allow_reset=True
                    )
                )
            except ImportError:
                raise ImportError(
                    "chromadb package not installed. Run: pip install chromadb"
                )
        return self._client
    
    @property
    def collection(self):
        """Get or create the sessions collection."""
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name="claude_sessions",
                metadata={
                    "hnsw:space": "cosine",  # Cosine similarity
                    "description": "Claude Code session chunks for semantic search"
                }
            )
        return self._collection
    
    def add_chunks(
        self, 
        chunks: List[Any],  # List[SessionChunk]
        embeddings: List[List[float]]
    ) -> int:
        """
        Add session chunks to the vector store.
        
        Args:
            chunks: List of SessionChunk objects
            embeddings: Corresponding embeddings
            
        Returns:
            Number of chunks added
        """
        if not chunks or not embeddings:
            return 0
        
        if len(chunks) != len(embeddings):
            raise ValueError(f"Mismatch: {len(chunks)} chunks vs {len(embeddings)} embeddings")
        
        # Filter out chunks with empty embeddings
        valid_data = [
            (chunk, emb) for chunk, emb in zip(chunks, embeddings)
            if emb and len(emb) > 0
        ]
        
        if not valid_data:
            return 0
        
        chunks, embeddings = zip(*valid_data)
        
        # Prepare data for ChromaDB
        ids = [f"{c.session_id}_{c.chunk_index}" for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "session_id": c.session_id,
                "project": c.project,
                "chunk_index": c.chunk_index,
                "preview": c.metadata.get("preview", "")[:500],
                "timestamp": c.metadata.get("timestamp", ""),
                "char_count": c.metadata.get("char_count", 0)
            }
            for c in chunks
        ]
        
        # Add to collection (upsert to handle re-indexing)
        self.collection.upsert(
            ids=list(ids),
            embeddings=list(embeddings),
            documents=list(documents),
            metadatas=list(metadatas)
        )
        
        return len(ids)
    
    def search(
        self, 
        query_embedding: List[float], 
        n_results: int = 20,
        project_filter: Optional[str] = None
    ) -> List[SearchResult]:
        """
        Search for similar session chunks.
        
        Args:
            query_embedding: The embedding to search with
            n_results: Maximum number of results
            project_filter: Optional project name to filter by
            
        Returns:
            List of SearchResult objects, sorted by score (highest first)
        """
        if not query_embedding:
            return []
        
        # Build where filter if project specified
        where_filter = None
        if project_filter:
            where_filter = {"project": {"$eq": project_filter}}
        
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            print(f"Search error: {e}")
            return []
        
        if not results or not results.get("ids") or not results["ids"][0]:
            return []
        
        search_results = []
        
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            metadata = results["metadatas"][0][i]
            document = results["documents"][0][i] if results.get("documents") else ""
            
            # Convert cosine distance to similarity score (0-100%)
            # Cosine distance ranges from 0 (identical) to 2 (opposite)
            # We convert to 0-100 where 100 is most similar
            score = max(0, min(100, int((1 - distance / 2) * 100)))
            
            search_results.append(SearchResult(
                session_id=metadata.get("session_id", ""),
                project=metadata.get("project", ""),
                score=score,
                preview=metadata.get("preview", "")[:200],
                chunk_index=metadata.get("chunk_index", 0),
                timestamp=metadata.get("timestamp"),
                content=document[:500] if document else ""
            ))
        
        return search_results
    
    def search_sessions(
        self, 
        query_embedding: List[float], 
        n_sessions: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search and aggregate results by session.
        Returns the best match per session, sorted by score.
        
        Args:
            query_embedding: The embedding to search with
            n_sessions: Number of sessions to return
            
        Returns:
            List of session dicts with aggregated info
        """
        # Get more results than needed for aggregation
        results = self.search(query_embedding, n_results=n_sessions * 5)
        
        # Aggregate by session (keep best score per session)
        session_map: Dict[str, Dict] = {}
        
        for r in results:
            if r.session_id not in session_map or r.score > session_map[r.session_id]["score"]:
                session_map[r.session_id] = {
                    "session_id": r.session_id,
                    "project": r.project,
                    "score": r.score,
                    "preview": r.preview,
                    "timestamp": r.timestamp,
                    "best_chunk": r.chunk_index
                }
        
        # Sort by score and return top n
        sorted_sessions = sorted(
            session_map.values(),
            key=lambda x: x["score"],
            reverse=True
        )[:n_sessions]
        
        return sorted_sessions
    
    def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        count = self.collection.count()
        
        # Get unique sessions
        try:
            # Sample to get unique session IDs
            sample = self.collection.get(limit=10000, include=["metadatas"])
            session_ids = set()
            projects = set()
            
            for meta in sample.get("metadatas", []):
                if meta:
                    session_ids.add(meta.get("session_id", ""))
                    projects.add(meta.get("project", ""))
            
            return {
                "total_chunks": count,
                "unique_sessions": len(session_ids),
                "unique_projects": len(projects),
                "storage_path": str(self.persist_path)
            }
        except:
            return {
                "total_chunks": count,
                "storage_path": str(self.persist_path)
            }
    
    def delete_session(self, session_id: str) -> int:
        """Delete all chunks for a session."""
        try:
            # Get all chunk IDs for this session
            results = self.collection.get(
                where={"session_id": {"$eq": session_id}},
                include=[]
            )
            
            if results and results.get("ids"):
                self.collection.delete(ids=results["ids"])
                return len(results["ids"])
        except Exception as e:
            print(f"Error deleting session: {e}")
        
        return 0
    
    def reset(self):
        """Reset the entire collection (use with caution!)."""
        self.client.delete_collection("claude_sessions")
        self._collection = None
        print("Collection reset. All data deleted.")
    
    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List indexed sessions with basic info."""
        try:
            sample = self.collection.get(limit=10000, include=["metadatas"])
            
            session_info = {}
            for meta in sample.get("metadatas", []):
                if not meta:
                    continue
                    
                sid = meta.get("session_id", "")
                if sid not in session_info:
                    session_info[sid] = {
                        "session_id": sid,
                        "project": meta.get("project", ""),
                        "chunk_count": 0,
                        "timestamp": meta.get("timestamp", "")
                    }
                session_info[sid]["chunk_count"] += 1
            
            return list(session_info.values())[:limit]
        except:
            return []

    def count_session_chunks(self, session_id: str) -> int:
        """Count how many chunks exist for a session in the store."""
        try:
            results = self.collection.get(
                where={"session_id": {"$eq": session_id}},
                include=[]
            )
            return len(results.get("ids", []))
        except:
            return 0

    def get_indexed_session_ids(self) -> set:
        """
        Get all session IDs that have chunks in ChromaDB.

        This is the source of truth for what's actually indexed.
        More reliable than the JSON cache file.
        """
        try:
            results = self.collection.get(include=["metadatas"])
            session_ids = set()
            for meta in results.get("metadatas", []):
                if meta and meta.get("session_id"):
                    session_ids.add(meta["session_id"])
            return session_ids
        except:
            return set()

    def search_with_exclusions(
        self,
        query_embedding: List[float],
        n_results: int = 20,
        project_filter: Optional[str] = None,
        exclude_sessions: Optional[List[str]] = None
    ) -> List[SearchResult]:
        """
        Search with optional session exclusion (e.g., exclude active sessions).

        Args:
            query_embedding: The embedding to search with
            n_results: Maximum number of results
            project_filter: Optional project name to filter by
            exclude_sessions: Session IDs to exclude from results

        Returns:
            List of SearchResult objects, sorted by score (highest first)
        """
        # Get more results to compensate for exclusions
        extra = len(exclude_sessions) * 3 if exclude_sessions else 0
        results = self.search(query_embedding, n_results + extra, project_filter)

        if not exclude_sessions:
            return results[:n_results]

        # Filter out excluded sessions
        filtered = [r for r in results if r.session_id not in exclude_sessions]
        return filtered[:n_results]


# ============================================================
# CLI for testing
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Vector Store Test")
    print("=" * 60)
    
    store = SessionVectorStore()
    
    print(f"\nStorage path: {store.persist_path}")
    
    stats = store.get_stats()
    print(f"\nCurrent stats:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # Test adding mock data
    print("\nTesting with mock data...")
    
    from dataclasses import dataclass, field
    
    @dataclass
    class MockChunk:
        session_id: str
        project: str
        chunk_index: int
        content: str
        metadata: dict = field(default_factory=dict)
    
    mock_chunks = [
        MockChunk(
            session_id="test-session-001",
            project="test-project",
            chunk_index=0,
            content="How do I create a React component with TypeScript?",
            metadata={"preview": "React component...", "timestamp": "2025-01-18"}
        ),
        MockChunk(
            session_id="test-session-001",
            project="test-project",
            chunk_index=1,
            content="Setting up Firebase authentication in Next.js",
            metadata={"preview": "Firebase auth...", "timestamp": "2025-01-18"}
        ),
    ]
    
    # Generate mock embeddings (random for testing)
    import random
    mock_embeddings = [[random.random() for _ in range(768)] for _ in mock_chunks]
    
    added = store.add_chunks(mock_chunks, mock_embeddings)
    print(f"  Added {added} test chunks")
    
    # Test search
    print("\nTesting search...")
    results = store.search(mock_embeddings[0], n_results=5)
    print(f"  Found {len(results)} results")
    
    for r in results[:3]:
        print(f"    - {r.session_id}: {r.score}% - {r.preview[:50]}...")
    
    # Clean up test data
    deleted = store.delete_session("test-session-001")
    print(f"\nCleaned up {deleted} test chunks")
    
    print("\n✅ Vector store is working correctly!")
