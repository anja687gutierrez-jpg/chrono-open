"""
Embedding Service using Ollama
Generates vector embeddings for semantic search.

Uses nomic-embed-text model (768 dimensions, 8192 token context).
"""

from typing import List, Optional
import time


class EmbeddingService:
    """Generate embeddings using Ollama's nomic-embed-text model."""
    
    def __init__(self, model: str = "nomic-embed-text"):
        self.model = model
        self._client = None
    
    @property
    def client(self):
        """Lazy load the ollama client."""
        if self._client is None:
            try:
                import ollama
                self._client = ollama
            except ImportError:
                raise ImportError(
                    "ollama package not installed. Run: pip install ollama"
                )
        return self._client
    
    def check_model_available(self) -> bool:
        """Check if the embedding model is available."""
        try:
            models = self.client.list()
            model_names = [m.get("name", "").split(":")[0] for m in models.get("models", [])]
            return self.model in model_names
        except Exception as e:
            print(f"Error checking models: {e}")
            return False
    
    def pull_model(self) -> bool:
        """Pull the embedding model if not available."""
        try:
            print(f"Pulling {self.model} model...")
            self.client.pull(self.model)
            print(f"Successfully pulled {self.model}")
            return True
        except Exception as e:
            print(f"Error pulling model: {e}")
            return False
    
    def embed(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: The text to embed
            
        Returns:
            List of floats (768 dimensions for nomic-embed-text)
        """
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        
        try:
            response = self.client.embed(model=self.model, input=text)
            return response["embeddings"][0]
        except Exception as e:
            raise RuntimeError(f"Embedding failed: {e}")
    
    def embed_batch(
        self, 
        texts: List[str], 
        batch_size: int = 10,
        show_progress: bool = True
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            batch_size: Number of texts to embed per API call
            show_progress: Whether to print progress
            
        Returns:
            List of embeddings (same order as input texts)
        """
        if not texts:
            return []
        
        # Filter out empty texts but track their positions
        valid_texts = []
        valid_indices = []
        for i, text in enumerate(texts):
            if text and text.strip():
                valid_texts.append(text)
                valid_indices.append(i)
        
        if not valid_texts:
            return [[] for _ in texts]
        
        embeddings = [[] for _ in texts]
        total_batches = (len(valid_texts) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(valid_texts))
            batch_texts = valid_texts[start_idx:end_idx]
            
            if show_progress:
                print(f"  Embedding batch {batch_num + 1}/{total_batches}...", end="\r")
            
            try:
                response = self.client.embed(model=self.model, input=batch_texts)
                batch_embeddings = response["embeddings"]
                
                # Map back to original positions
                for i, emb in enumerate(batch_embeddings):
                    original_idx = valid_indices[start_idx + i]
                    embeddings[original_idx] = emb
                    
            except Exception as e:
                print(f"\n  Warning: Batch {batch_num + 1} failed: {e}")
                # Try individual embeddings for this batch
                for i, text in enumerate(batch_texts):
                    try:
                        original_idx = valid_indices[start_idx + i]
                        embeddings[original_idx] = self.embed(text)
                    except:
                        pass
            
            # Small delay between batches to avoid overwhelming Ollama
            if batch_num < total_batches - 1:
                time.sleep(0.1)
        
        if show_progress:
            print(f"  Embedded {len(valid_texts)} texts" + " " * 20)
        
        return embeddings
    
    def get_embedding_dimension(self) -> int:
        """Get the dimension of embeddings from this model."""
        # nomic-embed-text produces 768-dimensional embeddings
        return 768


# ============================================================
# CLI for testing
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Embedding Service Test")
    print("=" * 60)
    
    service = EmbeddingService()
    
    # Check if model is available
    print(f"\nChecking for {service.model} model...")
    
    if not service.check_model_available():
        print(f"Model not found. Pulling {service.model}...")
        if not service.pull_model():
            print("Failed to pull model. Make sure Ollama is running:")
            print("  ollama serve")
            exit(1)
    else:
        print(f"Model {service.model} is available")
    
    # Test single embedding
    print("\nTesting single embedding...")
    test_text = "How do I create a React component with TypeScript?"
    
    try:
        embedding = service.embed(test_text)
        print(f"  Input: '{test_text}'")
        print(f"  Embedding dimension: {len(embedding)}")
        print(f"  First 5 values: {embedding[:5]}")
    except Exception as e:
        print(f"  Error: {e}")
        exit(1)
    
    # Test batch embedding
    print("\nTesting batch embedding...")
    test_texts = [
        "Building a dashboard with real-time updates",
        "Firebase authentication setup",
        "CSS grid layout for responsive design",
        "Python script for data processing",
        "API endpoint error handling"
    ]
    
    try:
        embeddings = service.embed_batch(test_texts)
        print(f"  Embedded {len(embeddings)} texts")
        for i, (text, emb) in enumerate(zip(test_texts, embeddings)):
            print(f"  {i+1}. '{text[:40]}...' -> {len(emb)} dims")
    except Exception as e:
        print(f"  Error: {e}")
        exit(1)
    
    print("\n✅ Embedding service is working correctly!")
