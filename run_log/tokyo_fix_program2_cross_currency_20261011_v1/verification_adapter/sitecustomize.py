"""Opt-in synchronous filesystem adapter for this sandbox's Marimo CLI check.

No lint rule, AST, test, installed module or notebook is changed.
Only the three read-only file predicates avoid asyncio.to_thread.
"""
import os
from pathlib import Path
if os.environ.get('TOKYO_P2_MARIMO_FS_ADAPTER') == '1':
    from marimo._utils import async_path
    async def exists(path):
        return Path(path).exists()
    async def isfile(path):
        return Path(path).is_file()
    async def isdir(path):
        return Path(path).is_dir()
    async_path.exists = exists
    async_path.isfile = isfile
    async_path.isdir = isdir
