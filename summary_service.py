"""
Summary Service - AI-generated executive summaries for sessions

Uses Ollama to generate concise summaries of what was accomplished
in each Claude Code session.
"""

import requests
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class SessionChunk:
    """Represents a chunk of session content."""
    content: str
    role: str = "unknown"


class SummaryService:
    """Generates executive summaries using Ollama."""

    def __init__(self, model: str = "llama3.2:latest"):
        self.model = model
        self.base_url = "http://localhost:11434"
        self.generate_url = f"{self.base_url}/api/generate"

    def check_model_available(self) -> bool:
        """Check if the model is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.ok:
                models = response.json().get("models", [])
                return any(m.get("name", "").startswith(self.model.split(":")[0])
                          for m in models)
        except:
            pass
        return False

    def generate_summary(
        self,
        chunks: List[SessionChunk],
        max_content_chars: int = 4000
    ) -> Optional[str]:
        """
        Generate an executive summary for a session.

        Args:
            chunks: List of session chunks
            max_content_chars: Maximum characters to include in prompt

        Returns:
            Executive summary string or None if generation fails
        """
        if not chunks:
            return None

        # Build context from chunks - prioritize user messages and assistant conclusions
        user_msgs = []
        assistant_msgs = []

        for chunk in chunks:
            content = chunk.content.strip()
            if chunk.role == "user" or content.startswith("USER:"):
                user_msgs.append(content[:500])
            elif chunk.role == "assistant" or content.startswith("ASSISTANT:"):
                # Get non-thinking content
                if "[Thinking:" not in content:
                    assistant_msgs.append(content[:500])

        # Combine: some user context + assistant conclusions
        context_parts = []

        # Add first few user messages to understand the request
        for msg in user_msgs[:3]:
            context_parts.append(msg)

        # Add last few assistant messages to see outcomes
        for msg in assistant_msgs[-3:]:
            context_parts.append(msg)

        context = "\n---\n".join(context_parts)
        if len(context) > max_content_chars:
            context = context[:max_content_chars] + "..."

        prompt = f"""Read this coding session and write ONE short sentence (max 80 chars) describing what was done.

Examples of good summaries:
- "Set up Firebase auth for Ops Portal dashboard"
- "Fixed date parsing bug in chrono time display"
- "Refactored user API with TypeScript types"
- "Deployed React app to Vercel with CI/CD"

Session:
{context}

Summary (one sentence, no bullet points, no labels):"""

        try:
            response = requests.post(
                self.generate_url,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 50  # Keep it short
                    }
                },
                timeout=120  # Longer timeout for first load
            )

            if response.ok:
                result = response.json().get("response", "").strip()

                # Remove common preambles
                preambles = [
                    "Here is a brief executive summary of the Claude Code session excerpt:",
                    "Here is a brief executive summary:",
                    "Here is the executive summary:",
                    "Executive summary:",
                    "Summary:",
                ]
                for preamble in preambles:
                    if result.lower().startswith(preamble.lower()):
                        result = result[len(preamble):].strip()

                # Clean up the result
                result = result.replace('"', '').replace("'", "")
                result = result.strip("*").strip("-").strip()

                # Take first sentence if multiple
                if ". " in result:
                    result = result.split(". ")[0] + "."

                # Limit length
                if len(result) > 100:
                    result = result[:97] + "..."

                return result if result else None

        except Exception as e:
            print(f"Summary generation error: {e}")

        return None

    def generate_summaries_batch(
        self,
        sessions_chunks: dict,
        show_progress: bool = True
    ) -> dict:
        """
        Generate summaries for multiple sessions.

        Args:
            sessions_chunks: Dict of session_id -> list of chunks
            show_progress: Whether to show progress

        Returns:
            Dict of session_id -> summary
        """
        summaries = {}
        total = len(sessions_chunks)

        for i, (session_id, chunks) in enumerate(sessions_chunks.items(), 1):
            if show_progress:
                print(f"  Generating summary {i}/{total}: {session_id[:8]}...", end="\r")

            summary = self.generate_summary(chunks)
            if summary:
                summaries[session_id] = summary

        if show_progress:
            print(f"  Generated {len(summaries)} summaries" + " " * 30)

        return summaries


# Quick test
if __name__ == "__main__":
    service = SummaryService()

    if service.check_model_available():
        print(f"✓ Model {service.model} available")

        # Test with sample content
        test_chunks = [
            SessionChunk("USER: Can you help me set up Firebase authentication for my dashboard?", "user"),
            SessionChunk("ASSISTANT: I'll help you set up Firebase auth. First, let's install the SDK...", "assistant"),
            SessionChunk("ASSISTANT: Successfully configured email/password authentication with secure rules.", "assistant"),
        ]

        summary = service.generate_summary(test_chunks)
        print(f"Test summary: {summary}")
    else:
        print(f"✗ Model {service.model} not available")
        print("  Try: ollama pull llama3.2")
