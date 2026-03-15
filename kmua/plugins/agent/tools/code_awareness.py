"""Code self-awareness tools for the agent.

This module provides secure code introspection capabilities for the agent,
allowing it to read its own codebase and understand other bot functionalities.

Security considerations:
- Only allows access to files within the project directory
- Blocks access to sensitive files (config, secrets, etc.)
- Limits file size and directory traversal depth
- Uses path sanitization to prevent directory traversal attacks
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from kmua.logger import logger

from . import datatype

# Project root directory (kmua-bot folder)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent

# File patterns to exclude for security
EXCLUDED_PATTERNS = [
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
    # Logs (may contain sensitive info)
    "*.log",
    "logs/**/*",
    "audit.log",
    # Cache and temporary files
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
    # Data directory (contains user data)
    "data/**/*",
    # Lock files
    "*.lock",
    # Documentation (not needed for code understanding)
    "docs/**/*",
    "*.md",
]

# Maximum file size to read (100KB)
MAX_FILE_SIZE = 100 * 1024

# Maximum directory depth for listing
MAX_DEPTH = 5

# Maximum files to return in a directory listing
MAX_FILES_PER_LISTING = 100


@dataclass
class FileInfo:
    """Information about a file or directory."""

    path: str
    name: str
    is_dir: bool
    size: int | None = None
    line_count: int | None = None


@dataclass
class DirectoryListing:
    """Result of listing a directory."""

    path: str
    entries: list[FileInfo] = field(default_factory=list)
    truncated: bool = False
    total_count: int = 0


def _is_path_safe(path: Path) -> bool:
    """Check if a path is within the project root and safe to access.

    Args:
        path: The path to check.

    Returns:
        True if the path is safe, False otherwise.
    """
    try:
        # Resolve to absolute path and check if it's within project root
        resolved = path.resolve()
        return str(resolved).startswith(str(PROJECT_ROOT.resolve()))
    except (OSError, ValueError):
        return False


def _is_excluded(path: Path) -> bool:
    """Check if a file matches any excluded pattern.

    Args:
        path: The path to check, relative to project root.

    Returns:
        True if the file should be excluded.
    """
    rel_path = path.relative_to(PROJECT_ROOT)
    rel_str = str(rel_path)
    rel_str_unix = rel_str.replace(os.sep, "/")

    for pattern in EXCLUDED_PATTERNS:
        # Check both unix-style and os-style paths
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_str_unix, pattern):
            return True
        # Check directory patterns
        if pattern.endswith("/**/*"):
            dir_pattern = pattern[:-4]
            if rel_str_unix.startswith(dir_pattern + "/") or rel_str.startswith(
                dir_pattern + os.sep
            ):
                return True
    return False


def _sanitize_path(requested_path: str) -> Path:
    """Sanitize a user-provided path to prevent directory traversal.

    Args:
        requested_path: The path requested by the user.

    Returns:
        A safe Path object within the project directory.

    Raises:
        ModelRetry: If the path is invalid or unsafe.
    """
    requested_path = requested_path.strip()

    # Reject absolute paths entirely
    if requested_path.startswith("/"):
        raise ModelRetry("Invalid path: absolute paths are not allowed")

    # Reject Windows-style absolute paths
    if len(requested_path) >= 2 and requested_path[1] == ":":
        raise ModelRetry("Invalid path: absolute paths are not allowed")

    # Prevent directory traversal attempts
    if ".." in requested_path.split("/") or ".." in requested_path.split("\\"):
        raise ModelRetry("Invalid path: directory traversal not allowed")

    # Construct full path
    full_path = PROJECT_ROOT / requested_path

    # Verify path is within project (final safety check)
    if not _is_path_safe(full_path):
        raise ModelRetry("Access denied: path is outside project directory")

    return full_path


async def list_my_code_files(
    ctx: RunContext[datatype.ContextDeps],
    path: str = "",
    include_python_only: bool = True,
    max_depth: int = 3,
) -> DirectoryListing | str:
    """List files in the codebase. Use this to explore project structure.

    When to use:
    - User asks what you can do -> list "kmua/plugins" directory
    - Need to find where a feature is implemented

    Args:
        path: Relative path from project root (e.g., "kmua/plugins"). Use "" for root.
        include_python_only: If True (default), show only .py files.
        max_depth: Max depth to traverse (1-5, default 3).

    Returns:
        DirectoryListing with file info, or error message.
    """
    if max_depth < 1 or max_depth > MAX_DEPTH:
        raise ModelRetry(f"max_depth must be between 1 and {MAX_DEPTH}")

    try:
        target_path = _sanitize_path(path)
    except ModelRetry:
        raise

    if not target_path.exists():
        return f"Path not found: {path}"

    # Handle single file case
    if target_path.is_file():
        if _is_excluded(target_path):
            return "Access denied: this file type is restricted"
        try:
            size = target_path.stat().st_size
            line_count = len(target_path.read_text(encoding="utf-8").splitlines())
            rel_path = target_path.relative_to(PROJECT_ROOT)
            return DirectoryListing(
                path=str(rel_path),
                entries=[
                    FileInfo(
                        path=str(rel_path),
                        name=target_path.name,
                        is_dir=False,
                        size=size,
                        line_count=line_count,
                    )
                ],
                total_count=1,
            )
        except Exception as e:
            logger.warning(f"Error reading file {target_path}: {e}")
            return f"Error reading file: {e}"

    # Handle directory case
    entries: list[FileInfo] = []
    total_count = 0
    truncated = False

    try:
        for root, dirs, files in os.walk(target_path):
            # Calculate current depth
            current_depth = len(Path(root).relative_to(target_path).parts)
            if current_depth >= max_depth:
                dirs[:] = []  # Don't go deeper

            # Filter out excluded directories
            dirs[:] = [
                d
                for d in dirs
                if not _is_excluded(Path(root) / d)
                and not d.startswith(".")
                and d != "__pycache__"
            ]

            for file in files:
                file_path = Path(root) / file

                # Skip excluded files
                if _is_excluded(file_path):
                    continue

                # Filter by extension if requested
                if include_python_only and not file.endswith(".py"):
                    continue

                total_count += 1

                # Only add to results if under limit
                if len(entries) < MAX_FILES_PER_LISTING:
                    rel_path = file_path.relative_to(PROJECT_ROOT)
                    try:
                        size = file_path.stat().st_size
                        entries.append(
                            FileInfo(
                                path=str(rel_path),
                                name=file,
                                is_dir=False,
                                size=size,
                            )
                        )
                    except OSError:
                        # File might have been deleted
                        pass

            # Also add directories
            for dir_name in dirs:
                dir_path = Path(root) / dir_name
                rel_path = dir_path.relative_to(PROJECT_ROOT)
                entries.append(
                    FileInfo(
                        path=str(rel_path),
                        name=dir_name,
                        is_dir=True,
                    )
                )

            if len(entries) > MAX_FILES_PER_LISTING:
                truncated = True
                entries = entries[:MAX_FILES_PER_LISTING]
                break

    except Exception as e:
        logger.error(f"Error listing directory {target_path}: {e}")
        return f"Error listing directory: {e}"

    rel_path = target_path.relative_to(PROJECT_ROOT)
    return DirectoryListing(
        path=str(rel_path) if str(rel_path) != "." else "",
        entries=sorted(entries, key=lambda x: (not x.is_dir, x.name)),
        truncated=truncated,
        total_count=total_count,
    )


async def read_my_code_file(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> str:
    """Read contents of a code file. Use after list_my_code_files to view implementation.

    When to use:
    - User asks how a command/feature works
    - Need to understand implementation details

    Args:
        path: Relative path (e.g., "kmua/plugins/help.py").
        start_line: Line to start from (1-indexed, default 1).
        max_lines: Lines to read (1-500, default 200).

    Returns:
        File contents with line numbers.
    """
    if max_lines < 1 or max_lines > 500:
        raise ModelRetry("max_lines must be between 1 and 500")

    if start_line < 1:
        raise ModelRetry("start_line must be >= 1")

    try:
        file_path = _sanitize_path(path)
    except ModelRetry:
        raise

    if not file_path.exists():
        return f"File not found: {path}"

    if not file_path.is_file():
        return f"Path is not a file: {path}"

    if _is_excluded(file_path):
        return "Access denied: this file type is restricted"

    try:
        # Check file size first
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            return f"File too large ({size} bytes). Maximum allowed: {MAX_FILE_SIZE} bytes."

        # Read file content
        content = file_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Calculate slice
        start_idx = start_line - 1
        end_idx = min(start_idx + max_lines, len(lines))

        if start_idx >= len(lines):
            return f"Start line {start_line} exceeds file length ({len(lines)} lines)"

        # Format output with line numbers
        result_lines = []
        if start_idx > 0:
            result_lines.append(f"... ({start_idx} lines above)")

        for i in range(start_idx, end_idx):
            line_num = i + 1
            line_content = lines[i]
            result_lines.append(f"{line_num:4d}: {line_content}")

        if end_idx < len(lines):
            remaining = len(lines) - end_idx
            result_lines.append(f"... ({remaining} lines below)")

        header = (
            f"File: {path} (lines {start_line}-{end_idx} of {len(lines)}, {size} bytes)"
        )
        return f"{header}\n{'=' * len(header)}\n" + "\n".join(result_lines)

    except UnicodeDecodeError:
        return "Error: File is not a text file or has unsupported encoding"
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return f"Error reading file: {e}"


async def search_my_code(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
    file_pattern: str = "*.py",
    max_results: int = 20,
) -> list[dict[str, Any]] | str:
    """Search for text in code files. Use to find where features/commands are implemented.

    When to use:
    - User mentions a command (e.g., "/help") -> search for it
    - Looking for a specific feature's code

    Search tips:
    - Commands: use "/command" format
    - Features: use short keywords like "bottle", "quote"

    Args:
        query: Text to search (min 2 chars).
        file_pattern: File glob pattern (default "*.py").
        max_results: Max results (1-50, default 20).

    Returns:
        List of matching files with line numbers.
    """
    if not query or len(query) < 2:
        raise ModelRetry("Query must be at least 2 characters")

    if max_results < 1 or max_results > 50:
        raise ModelRetry("max_results must be between 1 and 50")

    results: list[dict[str, Any]] = []

    try:
        for py_file in PROJECT_ROOT.rglob(file_pattern):
            # Skip excluded files
            if _is_excluded(py_file):
                continue

            # Skip files that are too large
            try:
                if py_file.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
                lines = content.splitlines()

                file_matches = []
                for i, line in enumerate(lines, 1):
                    if query in line:
                        # Get context (2 lines before and after)
                        context_start = max(0, i - 3)
                        context_end = min(len(lines), i + 2)
                        context = lines[context_start:context_end]
                        context_line_nums = list(
                            range(context_start + 1, context_end + 1)
                        )

                        file_matches.append(
                            {
                                "line": i,
                                "content": line.strip(),
                                "context": list(zip(context_line_nums, context)),
                            }
                        )

                if file_matches:
                    rel_path = py_file.relative_to(PROJECT_ROOT)
                    results.append(
                        {
                            "file": str(rel_path),
                            "matches": file_matches,
                            "total_matches": len(file_matches),
                        }
                    )

                    if len(results) >= max_results:
                        break

            except Exception:
                # Skip files we can't read
                continue

    except Exception as e:
        logger.error(f"Error searching code: {e}")
        return f"Error searching code: {e}"

    return results


async def get_my_codebase_overview(
    ctx: RunContext[datatype.ContextDeps],
) -> dict[str, Any]:
    """Get high-level overview of the project. Use first when user asks what you can do.

    Returns summary including:
    - Project description
    - List of all plugins
    - List of available agent tools

    Returns:
        Dict with project info, plugins list, and tools list.
    """
    overview = {
        "project_name": "kmua-bot",
        "description": "A Telegram bot with AI agent capabilities",
        "structure": {
            "kmua/plugins/": "Main bot features and commands",
            "kmua/plugins/agent/": "AI agent functionality (your home)",
            "kmua/plugins/agent/tools/": "Tools available to the agent",
            "kmua/database/": "Database models and operations",
            "kmua/common/": "Shared utilities and helpers",
            "kmua/services/": "External service integrations",
            "kmua/i18n/": "Internationalization and translations",
        },
        "key_features": [],
    }

    # Discover actual plugins
    plugins_dir = PROJECT_ROOT / "kmua" / "plugins"
    if plugins_dir.exists():
        plugins = []
        for item in plugins_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                plugins.append(item.name)
            elif (
                item.is_file()
                and item.suffix == ".py"
                and not item.name.startswith("_")
            ):
                plugins.append(item.stem)

        overview["discovered_plugins"] = sorted(plugins)

    # Discover agent tools
    agent_tools_dir = PROJECT_ROOT / "kmua" / "plugins" / "agent" / "tools"
    if agent_tools_dir.exists():
        tools = []
        for item in agent_tools_dir.iterdir():
            if (
                item.is_file()
                and item.suffix == ".py"
                and not item.name.startswith("_")
            ):
                tools.append(item.stem)
        overview["agent_tools"] = sorted(tools)

    return overview


# Export tools for registration
__all__ = [
    "list_my_code_files",
    "read_my_code_file",
    "search_my_code",
    "get_my_codebase_overview",
]
