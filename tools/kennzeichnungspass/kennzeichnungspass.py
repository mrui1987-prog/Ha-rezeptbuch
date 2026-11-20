#!/usr/bin/env python3
"""Aufruf des Lesers aus Add-on 3 (rezeptbuch_leser/app/leser/kennzeichnungspass.py) am PC – eine Fassung (K04-16)."""
import runpy
import sys
from pathlib import Path

ZIEL = Path(__file__).resolve().parents[2] / "rezeptbuch_leser" / "app" / "leser" / "kennzeichnungspass.py"
sys.path.insert(0, str(ZIEL.parent))
sys.argv[0] = str(ZIEL)
runpy.run_path(str(ZIEL), run_name="__main__")
