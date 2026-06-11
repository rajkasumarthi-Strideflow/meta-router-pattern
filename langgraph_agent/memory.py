"""
langgraph_agent/memory.py
--------------------------
Long-term memory layer using Mem0.

Enterprise analog: shared context layer — cross-session user profile store.
Agents retrieve only what they need for the current decision rather than
loading full history into the prompt. This is what makes memory practical
at enterprise scale.

Mem0 is used here with in-memory vector store (no API key needed for
prototype). In production, swap to Mem0 Cloud or self-hosted with a
persistent vector DB.
"""

import os
from typing import Optional
from mem0 import Memory

from shared.models import UserPreferences


# ---------------------------------------------------------------------------
# Mem0 configuration
# Uses in-memory store for the prototype — no external dependencies.
# Enterprise analog: configure to a persistent vector store (Qdrant, Pinecone)
# ---------------------------------------------------------------------------

_MEM0_CONFIG = {
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "travel_agent",
            "embedding_model_dims": 384,
            "on_disk": False,
        },
    },
    "llm": {
        "provider": "anthropic",
        "config": {
            "model":   "claude-haiku-4-5",
            "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        },
    },
    "embedder": {
        "provider": "huggingface",
        "config": {"model": "multi-qa-MiniLM-L6-cos-v1"},
    },
}


class PreferenceMemory:
    """
    Wraps Mem0 with typed preference read/write for the travel agent.

    Two operations:
      - save_preferences()  called after step 1 to persist user's stated prefs
      - load_preferences()  called at the start of each step to hydrate context

    Enterprise analog: cross-session context hydration at workflow start.
    """

    def __init__(self):
        try:
            self._mem = Memory.from_config(_MEM0_CONFIG)
            self._available = True
        except Exception:
            # Graceful fallback if Mem0 init fails (e.g. no embedding model)
            self._mem = None
            self._available = False
            self._fallback_store: dict[str, UserPreferences] = {}

    def save_preferences(self, prefs: UserPreferences) -> None:
        """Persist user preferences to Mem0 long-term memory."""
        if not self._available:
            self._fallback_store[prefs.user_id] = prefs
            return

        facts = []
        if prefs.preferred_airline:
            facts.append(f"Preferred airline: {prefs.preferred_airline}")
        if prefs.seat_preference:
            facts.append(f"Seat preference: {prefs.seat_preference}")
        if prefs.hotel_tier:
            facts.append(f"Hotel tier preference: {prefs.hotel_tier}")
        if prefs.budget_ceiling:
            facts.append(f"Total trip budget ceiling: USD {prefs.budget_ceiling}")
        if prefs.dietary:
            facts.append(f"Dietary requirement: {prefs.dietary}")

        if facts:
            self._mem.add(
                " | ".join(facts),
                user_id=prefs.user_id,
                metadata={"type": "travel_preferences"},
            )

    def load_preferences(self, user_id: str) -> UserPreferences:
        """
        Retrieve stored preferences for a user.
        Returns empty UserPreferences if none found — first-time user.
        """
        prefs = UserPreferences(user_id=user_id)

        if not self._available:
            return self._fallback_store.get(user_id, prefs)

        try:
            results = self._mem.search(
                "travel preferences airline seat hotel budget",
                user_id=user_id,
                limit=5,
            )
            for r in results:
                text = r.get("memory", "")
                # Simple keyword extraction from stored facts
                if "Preferred airline:" in text:
                    prefs.preferred_airline = text.split("Preferred airline:")[-1].split("|")[0].strip()
                if "Seat preference:" in text:
                    prefs.seat_preference = text.split("Seat preference:")[-1].split("|")[0].strip()
                if "Hotel tier preference:" in text:
                    prefs.hotel_tier = text.split("Hotel tier preference:")[-1].split("|")[0].strip()
                if "Total trip budget ceiling:" in text:
                    try:
                        val = text.split("USD")[-1].split("|")[0].strip()
                        prefs.budget_ceiling = float(val)
                    except ValueError:
                        pass
                if "Dietary requirement:" in text:
                    prefs.dietary = text.split("Dietary requirement:")[-1].split("|")[0].strip()
        except Exception:
            pass

        return prefs

    def update_preference(self, user_id: str, key: str, value: str) -> None:
        """Update a single preference (e.g. after user changes return date)."""
        prefs = self.load_preferences(user_id)
        setattr(prefs, key, value)
        self.save_preferences(prefs)


# Module-level singleton — shared across all LangGraph steps in a worker
preference_memory = PreferenceMemory()
