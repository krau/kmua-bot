from os import cpu_count
from pathlib import Path

from pyrogram.client import Client
from pyrogram.session.session import Session

from kmua.bot.kurigram_patch import install as install_kurigram_patch
from kmua.config import app_config

# kurigram/pyrogram serialize ALL MTProto crypto through a single
# ThreadPoolExecutor worker per session (Session.CRYPTO_EXECUTOR_WORKERS = 1):
# every outgoing request (mtproto.pack in session.send) and every incoming
# packet (mtproto.unpack in session.handle_packet) parks on that one thread,
# with no timeout on either await. Under concurrent file transfers (see
# max_concurrent_transmissions below) the queue saturates, WAIT_TIMEOUT (15s)
# fires for every invoke, and each retry re-enqueues more work - the backlog
# becomes self-sustaining and the session wedges (no updates, all calls time
# out) while the process stays alive. pack/unpack are pure functions of their
# inputs, so a few workers are safe and remove the single point of failure.
# setattr: the class attribute is inferred as Literal[1], so a direct
# assignment would be a type error in pyright/pyrefly.
setattr(Session, "CRYPTO_EXECUTOR_WORKERS", min(4, cpu_count() or 1))
# Workers reduce the chance of saturation but cannot prevent the deadlock:
# every crypto await is still unbounded, so a backlog that does form freezes
# whatever handler is mid-send (the dispatcher processes updates one at a
# time) and never drains. Bound every crypto job (see kurigram_patch).
install_kurigram_patch()


def _build_plugins_config() -> dict[str, object]:
    """Build plugin loading config.

    When agent is disabled, avoid importing any modules under `kmua.plugins.agent`
    so no agent handlers or side effects are loaded.
    """
    root = "kmua.plugins"
    if app_config.agent:
        return {"root": root}

    plugins_dir = Path(__file__).resolve().parent.parent / "plugins"
    include: list[str] = []
    for module_file in sorted(plugins_dir.rglob("*.py")):
        rel = module_file.relative_to(plugins_dir)
        if not rel.parts:
            continue
        if rel.parts[0] == "agent":
            continue
        if "__pycache__" in rel.parts:
            continue
        if module_file.stem == "__init__":
            continue
        include.append(".".join(rel.with_suffix("").parts))

    return {"root": root, "include": include}


client = Client(
    name=app_config.session_name,
    api_id=app_config.api_id,
    api_hash=app_config.api_hash,
    bot_token=app_config.token,
    workdir=app_config.workdir,
    plugins=_build_plugins_config(),
    ipv6=app_config.use_ipv6,
    sleep_threshold=300,
    max_concurrent_transmissions=min(32, (cpu_count() or 0) + 4),
)
