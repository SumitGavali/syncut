"""
conftest.py — Pytest configuration: add project root to sys.path so
all test files can import the core modules (config, confidence, drift,
sync_engine, robustness, rough_cut, etc.) without installing the package.
"""
import sys
import os

# Insert project root at start of sys.path
sys.path.insert(0, os.path.dirname(__file__))
