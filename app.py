"""ExpertAnything desktop entry point (PySide6).

Run with:
    python app.py
or:
    python main.py

Configure an LLM before launch to enable real knowledge extraction and
semantic tutoring (otherwise the app runs in deterministic fallback).
See .env.example for EXPERTANYTHING_LLM_* variables.
"""
from __future__ import annotations

from main import main as desktop_main

if __name__ == "__main__":
    desktop_main()
