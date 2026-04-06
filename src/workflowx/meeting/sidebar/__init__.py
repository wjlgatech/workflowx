"""Real-time Meeting Sidebar — Phase 3 of Meeting Intelligence Stack.

INTERNAL MEETINGS ONLY. Legal constraint: two-party consent required for
external parties in CA and 11 other states.

Architecture:
  Screenpipe (local audio) → Whisper (local transcription) → 30s chunks
  → Claude Haiku → suggestion overlay

consent_guard.py enforces the internal-only rule by checking calendar attendees.
"""
