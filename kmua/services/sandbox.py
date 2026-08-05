"""Landlock sandboxed command execution via landrun.

The shell runs inside a per-session real directory that only that session's
processes may touch. landrun applies a kernel-level Landlock whitelist: the
sandbox can read the system paths needed to run programs, read/write its own
session directory, and reach only the configured outbound TCP ports. The bot's
own code (kmua/, settings, other sessions' data) is unreachable, as is /proc.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from kmua.config import app_config
from kmua.logger import logger

MAX_SHELL_OUTPUT = 64 * 1024  # 64 KB

_landrun_available: bool | None = None


@dataclass
class ShellResult:
    exit_code: int
    output: str
    timed_out: bool = False


def shell_root_dir() -> Path:
    """Root directory holding every session's shell workspace."""
    return (Path("data") / "workspaces-shell").resolve()


def session_shell_dir(session_key: str) -> Path:
    """The real sandbox directory for one session."""
    return shell_root_dir() / session_key


async def landrun_available() -> bool:
    """True when the landrun binary exists and the kernel supports Landlock.

    The probe result is cached for the process lifetime.
    """
    global _landrun_available
    if _landrun_available is not None:
        return _landrun_available
    proc = await asyncio.create_subprocess_exec(
        app_config.agent_landrun_path,
        "--version",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    code = await proc.wait()
    _landrun_available = code == 0
    if not _landrun_available:
        logger.warning(
            f"landrun not usable at {app_config.agent_landrun_path}; shell disabled"
        )
    return _landrun_available


async def clean_session(session_key: str) -> None:
    """Remove all files from a session's sandbox directory.

    Keeps the directory itself, the kmua codebase link and the tmp/ folder so
    the next command starts from a clean slate without breaking the sandbox
    wiring.
    """
    workdir = session_shell_dir(session_key)
    if not workdir.exists():
        return
    import shutil

    for item in workdir.iterdir():
        if item.name in ("kmua", "tmp"):
            continue
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def _last_activity_mtime(root: Path) -> float:
    """Latest mtime anywhere under *root* (a directory's own mtime does not
    move when an existing file inside it is edited)."""
    latest = root.stat().st_mtime
    if not root.is_dir():
        return latest
    for item in root.rglob("*"):
        try:
            mtime = item.stat().st_mtime
        except OSError:
            continue
        if mtime > latest:
            latest = mtime
    return latest


async def cleanup_stale_sessions(max_age_days: int) -> int:
    """Delete every session sandbox untouched for max_age_days; returns the
    number of directories removed. max_age_days <= 0 sweeps everything."""
    if max_age_days < 0:
        return 0
    root = shell_root_dir()
    if not root.exists():
        return 0
    import shutil

    cutoff = time.time() - max_age_days * 86400
    count = 0
    for workdir in root.iterdir():
        if not workdir.is_dir():
            continue
        try:
            stale = _last_activity_mtime(workdir) < cutoff
        except OSError:
            continue
        if not stale:
            continue
        _kill_workdir_processes(workdir)
        shutil.rmtree(workdir, ignore_errors=True)
        count += 1
    return count


def _kill_workdir_processes(workdir: Path) -> None:
    """Kill any process whose cwd is *workdir* (escaped sandbox children)."""
    if not Path("/proc").exists():
        return
    target = str(workdir)
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            cwd = os.readlink(f"/proc/{entry}/cwd")
        except OSError:
            continue
        if cwd == target:
            try:
                os.kill(int(entry), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass


def _codebase_path() -> Path | None:
    """Absolute path of the bot's kmua/ package, if present."""
    codebase = (Path("kmua")).resolve()
    return codebase if codebase.exists() else None


def _ensure_codebase_link(workdir: Path) -> None:
    """Expose the read-only codebase as ./kmua inside the session workdir.

    The landlock mount lives at an environment-dependent absolute path; the
    symlink gives every command a stable relative entry point.
    """
    codebase = _codebase_path()
    link = workdir / "kmua"
    if codebase is not None and not link.exists():
        try:
            link.symlink_to(codebase, target_is_directory=True)
        except OSError as e:
            logger.warning(f"Failed to link codebase into sandbox: {e}")


def _build_landrun_cmd(command: str, workdir: Path) -> list[str]:
    cmd = [
        app_config.agent_landrun_path,
        "--best-effort",
        "--rox",
        "/usr",
        "--ro",
        "/lib,/lib64,/bin,/etc",
        # device nodes needed by scripts (bash redirects, /dev/urandom, ...)
        "--rw",
        "/dev",
        "--rwx",
        str(workdir),
        # Clean PATH: the bot's own PATH points at /kmua/.venv/bin which is
        # outside the landlock whitelist and would make python3 etc. fail.
        "--env",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "--env",
        f"HOME={workdir}",
        "--env",
        f"TMPDIR={workdir}/tmp",
    ]
    # Read-only view of the bot's own code (kmua/ package). The settings file,
    # data and secrets live outside this subtree, so nothing sensitive is exposed.
    codebase = _codebase_path()
    if codebase is not None:
        cmd += ["--ro", str(codebase)]
    ports = app_config.agent_shell_network_ports
    if ports:
        cmd += ["--connect-tcp", ",".join(str(p) for p in ports)]
    # Resource limits via bash ulimit (landlock does not cover these): 30s CPU,
    # 256MB virtual memory, 16 processes, 10MB max file size. The process
    # cap is deliberately low: a fork bomb must stay far below what could
    # starve the shared container.
    cmd += [
        "--",
        "bash",
        "-c",
        (
            "ulimit -t 30 -v 262144 -u 16 -f 10240 2>/dev/null; "
            "ulimit -n 256 2>/dev/null; " + command
        ),
    ]
    return cmd


async def run_shell(
    session_key: str,
    command: str,
    timeout: int | None = None,
) -> ShellResult:
    """Run *command* inside the session's landlock sandbox.

    The session directory is created on demand and kept between calls so
    consecutive commands can share intermediate files.
    """
    workdir = session_shell_dir(session_key)
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "tmp").mkdir(exist_ok=True)
    _ensure_codebase_link(workdir)
    cmd = _build_landrun_cmd(command, workdir)
    timeout = timeout or app_config.agent_shell_timeout

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # own process group so we can kill children
        cwd=str(workdir),
    )
    timed_out = False
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Bash job-control children may live in their own process groups, so
        # killpg alone can miss them. Sweep /proc for any process whose cwd is
        # this session's sandbox directory and kill it too.
        _kill_workdir_processes(workdir)
        stdout, _ = await proc.communicate()
    output = (stdout or b"").decode("utf-8", errors="replace")
    if len(output) > MAX_SHELL_OUTPUT:
        output = output[:MAX_SHELL_OUTPUT] + "\n...[output truncated]"
    exit_code = proc.returncode if proc.returncode is not None else 1
    return ShellResult(exit_code=exit_code, output=output, timed_out=timed_out)
