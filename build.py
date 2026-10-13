"""Build standalone binary with PyInstaller.

Usage:
    pip install pyinstaller
    python build.py

Output: dist/VirtualDM  (Mac/Linux) or dist/VirtualDM.exe (Windows)

The binary includes all Python deps + the ui/ folder.
Users need no Python installed — just run the binary and a browser opens.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent

args = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--name", "VirtualDM",
    "--add-data", f"ui{':' if sys.platform != 'win32' else ';'}ui",
    "--add-data", f"db{':' if sys.platform != 'win32' else ';'}db",
    "--hidden-import", "psycopg",
    "--hidden-import", "psycopg.adapt",
    "--hidden-import", "psycopg_pool",
    "--hidden-import", "mcp.server.fastmcp",
    "--hidden-import", "anthropic",
    "--hidden-import", "openai",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "starlette.routing",
    "--hidden-import", "charactercheck",
    "--hidden-import", "dotenv",
    "--collect-all", "mcp",
    "--collect-all", "anthropic",
    "--noconfirm",
    "launcher.py",
]

print("Building VirtualDM binary...")
result = subprocess.run(args, cwd=ROOT)
sys.exit(result.returncode)
