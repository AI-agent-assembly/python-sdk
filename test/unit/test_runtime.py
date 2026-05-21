"""Unit tests for agent_assembly.runtime (AAASM-1227 / F115).

Covers the four scenarios from the AAASM-1230 AC checklist:
  * binary-in-PATH
  * binary-bundled (in agent_assembly/bin/aasm)
  * binary-not-found
  * already-running (init_assembly skips spawn when sidecar reachable)
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_assembly import runtime
