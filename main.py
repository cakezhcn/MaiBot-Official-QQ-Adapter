"""
main.py – Entry point for the MaiBot Official QQ Adapter.

Usage:
    python main.py

Configuration is read from config/config.toml (or the path given by the
QQ_ADAPTER_CONFIG environment variable).
"""

import logging
import os
import sys
from pathlib import Path

import toml
import botpy

from adapter import MaiBotClient, QQOfficialBotAdapter

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "config.toml"


def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: Config file not found: {path}", file=sys.stderr)
        print(
            "Copy config/config_example.toml to config/config.toml and fill in "
            "your credentials.",
            file=sys.stderr,
        )
        sys.exit(1)
    return toml.load(path)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def configure_logging(cfg: dict) -> None:
    log_cfg = cfg.get("logging", {})
    level_name: str = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_file: str = log_cfg.get("log_file", "")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    config_path = Path(os.environ.get("QQ_ADAPTER_CONFIG", _DEFAULT_CONFIG_PATH))
    cfg = load_config(config_path)
    configure_logging(cfg)

    logger = logging.getLogger(__name__)

    qq_cfg = cfg["qq"]
    maibot_cfg = cfg["maibot"]

    app_id: str = str(qq_cfg["app_id"])
    app_secret: str = str(qq_cfg["app_secret"])

    # Build intents based on config. Defaults to public messages + direct
    # message + group/C2C events, which covers most use cases.
    intents_cfg: dict = qq_cfg.get("intents", {})
    if isinstance(intents_cfg, int):
        # Legacy: numeric intents bitmask → just use the defaults
        logger.warning(
            "Numeric 'intents' in config is ignored; "
            "set individual intent flags instead."
        )
        intents_cfg = {}

    intents = botpy.Intents(
        public_messages=bool(intents_cfg.get("public_messages", True)),
        public_guild_messages=bool(intents_cfg.get("public_guild_messages", True)),
        direct_message=bool(intents_cfg.get("direct_message", True)),
        guild_messages=bool(intents_cfg.get("guild_messages", False)),
    )

    # MaiBotClient connects to MaiBot's WebSocket server.
    server_url: str = maibot_cfg.get(
        "server_url", "ws://localhost:8080/ws"
    )
    maibot_token: str | None = maibot_cfg.get("token") or None

    maibot_client = MaiBotClient(
        server_url=server_url,
        platform="qq_official",
        token=maibot_token,
    )

    # QQOfficialBotAdapter inherits botpy.Client and handles QQ events.
    adapter = QQOfficialBotAdapter(
        maibot_client=maibot_client,
        intents=intents,
    )

    logger.info(
        "Starting MaiBot Official QQ Adapter "
        "(app_id=%s, maibot=%s)…",
        app_id,
        server_url,
    )

    # botpy.Client.run() creates and manages the event loop internally.
    adapter.run(appid=app_id, secret=app_secret)


if __name__ == "__main__":
    main()
