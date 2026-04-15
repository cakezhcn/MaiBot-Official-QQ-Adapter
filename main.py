"""
main.py – Entry point for the MaiBot Official QQ Adapter.

Usage:
    python main.py

Configuration is read from config/config.toml (or the path given by the
QQ_ADAPTER_CONFIG environment variable).
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

import toml

from adapter import Auth, APIClient, EventHandler, QQAdapter

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
# AdapterManager
# ---------------------------------------------------------------------------


class AdapterManager:
    def __init__(self, config: dict):
        self.config = config

    def _build_adapter(self) -> QQAdapter:
        qq_cfg = self.config["qq"]
        maibot_cfg = self.config["maibot"]

        auth = Auth(
            app_id=qq_cfg["app_id"],
            app_secret=qq_cfg["app_secret"],
            auth_url=qq_cfg.get(
                "auth_url", "https://bots.qq.com/app/getAppAccessToken"
            ),
        )
        api_client = APIClient(
            auth=auth,
            api_base_url=qq_cfg.get("api_base_url", "https://api.sgroup.qq.com"),
        )
        event_handler = EventHandler(
            maibot_url=maibot_cfg["message_handler_url"],
        )
        return QQAdapter(
            auth=auth,
            api_client=api_client,
            event_handler=event_handler,
            intents=int(qq_cfg.get("intents", 1073741825)),
        )

    def start(self) -> None:
        adapter = self._build_adapter()
        logger = logging.getLogger(__name__)
        logger.info("Starting QQ Official Bot Adapter…")
        try:
            asyncio.run(adapter.run())
        except KeyboardInterrupt:
            logger.info("Adapter stopped by user.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config_path = Path(os.environ.get("QQ_ADAPTER_CONFIG", _DEFAULT_CONFIG_PATH))
    cfg = load_config(config_path)
    configure_logging(cfg)
    manager = AdapterManager(cfg)
    manager.start()
