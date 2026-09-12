"""Code repository loader for agentfs.

This module initializes the agentfs virtual filesystem with a sanitized copy
of the project codebase, providing true isolation from the host filesystem.
"""

from __future__ import annotations

import fnmatch
import functools
from pathlib import Path
from typing import Any

from agentfs_sdk import AgentFS, AgentFSOptions

from kmua.config import app_config
from kmua.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# Default excluded patterns (security-sensitive, always excluded)
DEFAULT_EXCLUDED_PATTERNS = [
    # Config files
    "settings.toml",
    "settings.dev.toml",
    "settings.*.toml",
    ".env",
    ".env.*",
    "*.env",
    # Secrets
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "secrets.*",
    "*secret*",
    "*credential*",
    "*password*",
    "*token*",
    # Database files
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    # Logs
    "*.log",
    "logs/**/*",
    "audit.log",
    # Cache
    "__pycache__/**/*",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/**/*",
    ".ruff_cache/**/*",
    ".mypy_cache/**/*",
    ".venv/**/*",
    "venv/**/*",
    "*.egg-info/**/*",
    # Git
    ".git/**/*",
    ".gitignore",
    # Docker
    ".dockerignore",
    # Data directory
    "data/**/*",
    # Lock files
    "*.lock",
]

MAX_FILE_SIZE = 100 * 1024

_code_agentfs: AgentFS | None = None


def _is_excluded(rel_path: Path, extra_patterns: list[str] | None = None) -> bool:
    """Return True if rel_path matches a default or extra exclusion pattern."""
    rel_str = str(rel_path).replace("\\", "/")

    # Check default patterns (always excluded for security)
    for pattern in DEFAULT_EXCLUDED_PATTERNS:
        if _match_pattern(rel_str, pattern):
            return True

    if extra_patterns:
        for pattern in extra_patterns:
            if _match_pattern(rel_str, pattern):
                return True

    return False


def _match_pattern(rel_str: str, pattern: str) -> bool:
    """Match a path against a pattern with proper glob support.

    Supports:
    - Standard fnmatch patterns (*, ?, [seq])
    - /** or /**/* for matching directory and all its contents
    """
    pattern = pattern.replace("\\", "/").rstrip("/")

    # Handle /** or /**/* suffix - match directory and all its contents
    if "/**" in pattern:
        dir_prefix = pattern.split("/**")[0]
        if rel_str == dir_prefix or rel_str.startswith(dir_prefix + "/"):
            return True

    if fnmatch.fnmatch(rel_str, pattern):
        return True

    # "kmua/plugins/extra" also matches "kmua/plugins/extra/file.py"
    if not pattern.endswith("*") and "/" in pattern:
        if rel_str.startswith(pattern + "/"):
            return True

    return False


async def init_code_repository(
    extra_exclude_patterns: list[str] | None = None,
) -> AgentFS:
    """Initialize the agentfs virtual filesystem with project codebase.

    This creates an isolated copy of the project code in agentfs,
    excluding sensitive files. The agent can only access files within
    this virtual filesystem.

    Args:
        extra_exclude_patterns: Additional file patterns to exclude (optional).
            These are combined with the default security exclusions.

    Returns:
        AgentFS instance configured with the code repository.
    """
    global _code_agentfs

    if _code_agentfs is not None:
        return _code_agentfs

    logger.info("Initializing code repository in agentfs...")

    config_patterns: list[str] = getattr(app_config, "agent_code_exclude_patterns", [])

    all_extra_patterns = list(config_patterns) if config_patterns else []
    if extra_exclude_patterns:
        all_extra_patterns.extend(extra_exclude_patterns)

    seen = set()
    unique_patterns = []
    for p in all_extra_patterns:
        if p not in seen:
            seen.add(p)
            unique_patterns.append(p)
    all_extra_patterns = unique_patterns

    agent = await AgentFS.open(AgentFSOptions(id="kmua-codebase"))

    try:
        await agent.fs.unlink("/")
    except Exception:
        pass  # Directory might not exist

    # Load Python files into agentfs (only from kmua directory, exclude venv)
    loaded_count = 0
    skipped_count = 0

    kmua_dir = PROJECT_ROOT / "kmua"
    if not kmua_dir.exists():
        logger.error("kmua directory not found")
        return agent

    for py_file in kmua_dir.rglob("*.py"):
        try:
            rel_path = py_file.relative_to(PROJECT_ROOT)
        except ValueError:
            continue

        if _is_excluded(rel_path, all_extra_patterns):
            skipped_count += 1
            continue

        try:
            if py_file.stat().st_size > MAX_FILE_SIZE:
                logger.debug(f"Skipping large file: {rel_path}")
                skipped_count += 1
                continue
        except OSError:
            continue

        try:
            content = py_file.read_text(encoding="utf-8")
            agentfs_path = f"/{rel_path}"

            parent = Path(agentfs_path).parent
            if str(parent) != "/":
                try:
                    await agent.fs.mkdir(str(parent))
                except Exception:
                    pass  # Directory might already exist

            await agent.fs.write_file(agentfs_path, content)
            loaded_count += 1

        except Exception as e:
            logger.warning(f"Failed to load {rel_path}: {e}")
            skipped_count += 1

    await agent.kv.set(
        "codebase:meta",
        {
            "project_root": str(PROJECT_ROOT),
            "loaded_files": loaded_count,
            "skipped_files": skipped_count,
            "max_file_size": MAX_FILE_SIZE,
        },
    )

    _code_agentfs = agent
    logger.info(
        f"Code repository initialized: {loaded_count} files loaded, {skipped_count} skipped"
    )

    return agent


async def get_code_agentfs() -> AgentFS | None:
    """Return the initialized code repository agentfs, or None."""
    return _code_agentfs


async def close_code_repository() -> None:
    """Close the code repository agentfs instance."""
    global _code_agentfs
    if _code_agentfs is not None:
        await _code_agentfs.close()
        _code_agentfs = None
        logger.info("Code repository closed")


async def list_files(
    path: str = "/", include_dirs: bool = True
) -> list[dict[str, Any]]:
    """List files and directories in the virtual filesystem."""
    agent = await get_code_agentfs()
    if agent is None:
        raise RuntimeError("Code repository not initialized")

    try:
        entries = await agent.fs.readdir(path)
        result = []

        for name in entries:
            entry_path = f"{path}/{name}" if path != "/" else f"/{name}"

            try:
                stats = await agent.fs.stat(entry_path)
                is_dir = stats.is_directory()

                if not include_dirs and is_dir:
                    continue

                entry_info = {
                    "name": name,
                    "path": entry_path,
                    "is_dir": is_dir,
                    "size": stats.size if not is_dir else None,
                }

                if not is_dir:
                    try:
                        content = await agent.fs.read_file(entry_path)
                        entry_info["line_count"] = len(content.splitlines())
                    except Exception:
                        entry_info["line_count"] = None

                result.append(entry_info)

            except Exception:
                continue

        return result

    except Exception as e:
        logger.error(f"Error listing files in {path}: {e}")
        return []


async def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> str | None:
    """Read file contents from the virtual filesystem.

    start_line is 1-indexed; returns None if not found.
    """
    agent = await get_code_agentfs()
    if agent is None:
        raise RuntimeError("Code repository not initialized")

    try:
        content: str = await agent.fs.read_file(path)  # type: ignore
        lines: list[str] = content.splitlines()

        start_idx = start_line - 1
        if start_idx >= len(lines):
            return None

        end_idx = min(start_idx + max_lines, len(lines))
        selected_lines = lines[start_idx:end_idx]

        result_lines = []
        if start_idx > 0:
            result_lines.append(f"... ({start_idx} lines above)")

        for i, line in enumerate(selected_lines, start=start_line):
            result_lines.append(f"{i:4d}: {line}")

        if end_idx < len(lines):
            result_lines.append(f"... ({len(lines) - end_idx} lines below)")

        header = f"File: {path} (lines {start_line}-{end_idx} of {len(lines)})"
        return f"{header}\n{'=' * len(header)}\n" + "\n".join(result_lines)

    except Exception as e:
        logger.debug(f"Error reading file {path}: {e}")
        return None


@functools.lru_cache
async def search_in_files(
    query: str,
    max_results: int = 20,
    use_regex: bool = False,
    case_sensitive: bool = True,
) -> list[dict[str, Any]]:
    """Search for text or a regex pattern across all files in the virtual filesystem.

    max_results caps the number of matching files returned.
    """
    import re

    agent = await get_code_agentfs()
    if agent is None:
        raise RuntimeError("Code repository not initialized")

    pattern = None
    query_lower = None
    if use_regex:
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            pattern = re.compile(query, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")
    elif not case_sensitive:
        query_lower = query.lower()

    results = []

    async def search_directory(dir_path: str) -> None:
        nonlocal results

        if len(results) >= max_results:
            return

        try:
            entries = await agent.fs.readdir(dir_path)

            for name in entries:
                if len(results) >= max_results:
                    return

                entry_path = f"{dir_path}/{name}" if dir_path != "/" else f"/{name}"

                try:
                    stats = await agent.fs.stat(entry_path)

                    if stats.is_directory():
                        await search_directory(entry_path)
                    else:
                        from typing import cast

                        content = cast(str, await agent.fs.read_file(entry_path))
                        lines = content.splitlines()

                        file_matches: list[dict[str, Any]] = []
                        for i, line in enumerate(lines, 1):
                            if use_regex:
                                assert pattern is not None  # for type checker
                                if pattern.search(line):
                                    file_matches.append(
                                        {
                                            "line": i,
                                            "content": line.strip(),
                                        }
                                    )
                            else:
                                if case_sensitive:
                                    if query in line:
                                        file_matches.append(
                                            {
                                                "line": i,
                                                "content": line.strip(),
                                            }
                                        )
                                else:
                                    assert query_lower is not None  # for type checker
                                    if query_lower in line.lower():
                                        file_matches.append(
                                            {
                                                "line": i,
                                                "content": line.strip(),
                                            }
                                        )

                        if file_matches:
                            results.append(
                                {
                                    "file": entry_path,
                                    "matches": file_matches,
                                    "total_matches": len(file_matches),
                                }
                            )

                except Exception:
                    continue

        except Exception:
            pass

    await search_directory("/")
    return results


async def get_repository_info() -> dict[str, Any]:
    """Return metadata about the loaded code repository, with file and directory counts."""
    agent = await get_code_agentfs()
    if agent is None:
        return {"error": "Code repository not initialized"}

    meta = await agent.kv.get("codebase:meta") or {}

    file_count = 0
    dir_count = 0

    async def count_entries(dir_path: str) -> None:
        nonlocal file_count, dir_count

        try:
            entries = await agent.fs.readdir(dir_path)

            for name in entries:
                entry_path = f"{dir_path}/{name}" if dir_path != "/" else f"/{name}"

                try:
                    stats = await agent.fs.stat(entry_path)
                    if stats.is_directory():
                        dir_count += 1
                        await count_entries(entry_path)
                    else:
                        file_count += 1
                except Exception:
                    continue
        except Exception:
            pass

    await count_entries("/")

    return {
        "project_name": "kmua-bot",
        "description": "A Telegram bot with AI agent capabilities",
        "virtual_files": file_count,
        "virtual_directories": dir_count,
        **meta,
    }
