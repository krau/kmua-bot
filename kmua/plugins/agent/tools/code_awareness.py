"""Tools for reading your own codebase."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import ModelRetry, RunContext

from kmua.logger import logger

from . import datatype
from .code_repo import (
    get_repository_info,
    list_files,
    read_file,
    search_in_files,
)


@dataclass
class FileInfo:
    path: str
    name: str
    is_dir: bool
    size: int | None = None
    line_count: int | None = None


@dataclass
class DirectoryListing:
    path: str
    entries: list[FileInfo] = field(default_factory=list)
    truncated: bool = False
    total_count: int = 0


async def list_my_code_files(
    ctx: RunContext[datatype.ContextDeps],
    path: str = "/",
    include_python_only: bool = True,
    max_depth: int = 3,
) -> DirectoryListing | str:
    """List files and directories in your codebase.

    Use when:
    - User asks what you can do -> list "/kmua/plugins"
    - Looking for a specific feature's location

    Args:
        path: Directory path (e.g., "/kmua/plugins"). Use "/" for root.
        include_python_only: If True (default), show only .py files.
        max_depth: How deep to go (1-7, default 3).

    Returns:
        Directory listing with file information.
    """
    if max_depth < 1 or max_depth > 7:
        raise ModelRetry("max_depth must be between 1 and 7")

    try:
        if not path.startswith("/"):
            path = "/" + path

        entries = await list_files(path, include_dirs=True)

        if not entries:
            return f"Path not found: {path}"

        filtered_entries: list[FileInfo] = []
        total_count = 0

        for entry in entries:
            is_dir = entry.get("is_dir", False)
            name = entry.get("name", "")

            if name.startswith("."):
                continue

            if not is_dir and include_python_only and not name.endswith(".py"):
                continue

            total_count += 1

            if len(filtered_entries) < 100:
                filtered_entries.append(
                    FileInfo(
                        path=entry.get("path", ""),
                        name=name,
                        is_dir=is_dir,
                        size=entry.get("size"),
                        line_count=entry.get("line_count"),
                    )
                )

        truncated = len(filtered_entries) < total_count

        sorted_entries = sorted(
            filtered_entries, key=lambda x: (not x.is_dir, x.name.lower())
        )

        return DirectoryListing(
            path=path,
            entries=sorted_entries,
            truncated=truncated,
            total_count=total_count,
        )

    except Exception as e:
        logger.error(f"Error listing files: {e}")
        return f"Error: {e}"


async def read_my_code_file(
    ctx: RunContext[datatype.ContextDeps],
    path: str,
    start_line: int = 1,
    max_lines: int = 200,
) -> str:
    """Read a code file's contents.

    Use when:
    - User asks how a specific feature/command works
    - Need to see implementation details

    Args:
        path: File path (e.g., "/kmua/plugins/help.py").
        start_line: Line to start from (1-indexed, default 1).
        max_lines: Max lines to read (1-1500, default 200).

    Returns:
        File contents with line numbers.
    """
    if max_lines < 1 or max_lines > 1500:
        raise ModelRetry("max_lines must be between 1 and 1500")

    if start_line < 1:
        raise ModelRetry("start_line must be >= 1")

    try:
        if not path.startswith("/"):
            path = "/" + path

        content = await read_file(path, start_line=start_line, max_lines=max_lines)

        if content is None:
            return f"File not found: {path}"

        return content

    except Exception as e:
        logger.error(f"Error reading file: {e}")
        return f"Error: {e}"


async def search_my_code(
    ctx: RunContext[datatype.ContextDeps],
    query: str,
    max_results: int = 20,
) -> str:
    """Search through your codebase for specific text.

    Use when:
    - User mentions a command (e.g., "/help") and you need to find its implementation
    - Looking for where a feature is defined

    Tips:
    - Commands: search for "/commandname"
    - Features: search for keywords like "bottle", "waifu", "quote"

    Args:
        query: Text to search for (min 2 characters).
        max_results: Max number of results (1-50, default 20).

    Returns:
        Formatted text showing matching code snippets with file paths and line numbers.
    """
    if not query or len(query) < 2:
        raise ModelRetry("Query must be at least 2 characters")

    if max_results < 1 or max_results > 50:
        raise ModelRetry("max_results must be between 1 and 50")

    try:
        results = await search_in_files(query, max_results=max_results)

        if not results:
            return f"No results found for '{query}'"

        # Format results as readable text
        output_parts = []
        output_parts.append(f"Search results for '{query}' ({len(results)} files):\n")

        for i, result in enumerate(results, 1):
            file_path = result.get("file", "unknown")
            matches = result.get("matches", [])
            total_matches = result.get("total_matches", len(matches))

            output_parts.append(f"\n{i}. {file_path} ({total_matches} matches)")
            output_parts.append("-" * 60)

            # Show first 3 matches with context
            for j, match in enumerate(matches[:3], 1):
                line_num = match.get("line", 0)
                content = match.get("content", "")
                output_parts.append(f"   Line {line_num}: {content}")

            if len(matches) > 3:
                output_parts.append(f"   ... and {len(matches) - 3} more matches")

        return "\n".join(output_parts)

    except Exception as e:
        logger.error(f"Error searching code: {e}")
        return f"Error: {e}"


async def get_my_codebase_overview(
    ctx: RunContext[datatype.ContextDeps],
) -> dict[str, Any]:
    """Get an overview of your capabilities.

    Use first when user asks "what can you do" or "what features do you have".

    Returns:
        Dict with project info and list of available plugins/features.
    """
    try:
        info = await get_repository_info()

        plugins = []
        try:
            plugin_entries = await list_files("/kmua/plugins", include_dirs=True)
            for entry in plugin_entries:
                if entry.get("is_dir"):
                    name = entry.get("name", "")
                    if not name.startswith("_"):
                        plugins.append(name)
                elif entry.get("name", "").endswith(".py"):
                    name = entry.get("name", "")[:-3]
                    if not name.startswith("_"):
                        plugins.append(name)

            plugins.sort()
        except Exception:
            pass

        return {
            "project_name": info.get("project_name", "kmua-bot"),
            "description": info.get(
                "description", "A Telegram bot with AI agent capabilities"
            ),
            "plugins": plugins,
        }

    except Exception as e:
        logger.error(f"Error getting overview: {e}")
        return {"error": str(e)}


__all__ = [
    "list_my_code_files",
    "read_my_code_file",
    "search_my_code",
    "get_my_codebase_overview",
]
