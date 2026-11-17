#!/usr/bin/env python3
"""Create the per-user macOS LaunchAgent for Mnemos' host model supervisor."""

import os
import plistlib
import sys
from pathlib import Path


project_dir = Path(__file__).resolve().parent.parent
launch_agents = Path.home() / "Library" / "LaunchAgents"
launch_agents.mkdir(parents=True, exist_ok=True)
plist_path = launch_agents / "com.mnemos.model-supervisor.plist"
environment = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
}
if os.environ.get("DOC_AI_MODEL_PATH"):
    environment["DOC_AI_MODEL_PATH"] = os.environ["DOC_AI_MODEL_PATH"]

configuration = {
    "Label": "com.mnemos.model-supervisor",
    "ProgramArguments": [sys.executable, str(project_dir / "scripts" / "model_supervisor.py")],
    "WorkingDirectory": str(project_dir),
    "EnvironmentVariables": environment,
    "RunAtLoad": True,
    "KeepAlive": False,
    "ProcessType": "Background",
    "StandardOutPath": "/tmp/mnemos-model-supervisor.log",
    "StandardErrorPath": "/tmp/mnemos-model-supervisor.log",
}
plist_path.write_bytes(plistlib.dumps(configuration))
plist_path.chmod(0o600)
print(plist_path)
