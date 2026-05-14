"""Shared pytest fixtures."""
from __future__ import annotations

import os

# Default to stub classifier transport during tests.
os.environ.setdefault("DH_CLASSIFIER_TRANSPORT", "stub")
os.environ.setdefault("DH_DB_PASSWORD", "test-password")
os.environ.setdefault("DH_ENV", "dev")
os.environ.setdefault("DH_LOG_LEVEL", "WARNING")
