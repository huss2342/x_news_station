"""Program entrypoint for X-News-Station."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import config
from modules.news_fetcher import get_monitor
from modules.radio_loop import RadioStation
from modules.runtime_settings import (
    RuntimeCliOverrides,
    RuntimeSettings,
    apply_cli_overrides,
    apply_runtime_settings,
    create_settings_example_file,
    create_settings_file,
    load_runtime_settings,
)

STARTUP_BANNER_LINES = (
    "==================================================================",
    "X  N  E  W  S  -  S  T  A  T  I  O  N",
    "Twitter-to-Radio News Station",
    "==================================================================",
)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="X-News-Station: A Twitter-to-Radio news broadcast system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py                  # Open the launcher GUI\n"
            "  python main.py --no-gui         # Run station headless with current settings\n"
            "  python main.py --gui            # Compatibility alias for GUI launch\n"
            "  python main.py --health-check   # Verify provider, audio, music, and twitter setup\n"
            "  python main.py --smoke-test     # Run a bounded functional test and exit\n"
            "  python main.py --mock           # Use mock Twitter data for testing\n"
            "  python main.py --voice bf_emma  # Use British female voice\n"
            "  python main.py --no-music       # Run without background music\n"
            "  python main.py --config custom.ini\n"
            "  python main.py --init-config    # Create shareable settings template"
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(config.get_settings_file()),
        help=f"Path to runtime settings file (default: {config.SETTINGS_FILE})",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create runtime settings template file and exit",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the settings launcher GUI (compatibility alias; GUI is the default)",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run the station directly instead of opening the launcher GUI",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run runtime health checks and exit",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a bounded functional smoke test and exit",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force use of mock Twitter data instead of real API",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=None,
        help="Override voice ID from settings file",
    )
    parser.add_argument(
        "--no-music",
        action="store_true",
        help="Disable background music",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override log level from settings file",
    )
    return parser.parse_args()


def setup_logging(log_level: str) -> None:
    """Configure console and file logging handlers."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = config.get_log_file()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError as exc:
        logging.basicConfig(level=getattr(logging, log_level), format=log_format, handlers=handlers, force=True)
        logging.getLogger(__name__).warning("Failed to open log file %s: %s", log_file, exc)
        return

    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_format,
        handlers=handlers,
        force=True,
    )
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized (level=%s)", log_level)
    logger.info("Log file: %s", log_file)


def log_banner(logger: logging.Logger, settings: RuntimeSettings) -> None:
    """Log startup banner and effective runtime settings."""
    for line in STARTUP_BANNER_LINES:
        logger.info(line)

    logger.info("Configuration:")
    logger.info("  Twitter Accounts: %s", ", ".join(settings.twitter_accounts))
    logger.info("  Check Interval: %ss", settings.fetch_interval_seconds)
    logger.info("  Recap Interval: %ss", settings.recap_interval_seconds)
    logger.info("  LLM Provider: %s", settings.llm_provider)
    if settings.llm_provider == "openai_compatible":
        logger.info("  API Base URL: %s", settings.llm_api_base_url)
        logger.info("  API Model: %s", settings.llm_api_model)
    elif settings.llm_provider == "simple":
        logger.info("  Rewriter Mode: Simple fallback only")
    else:
        logger.info("  Ollama Model: %s", settings.ollama_model)
        logger.info("  Ollama Base URL: %s", settings.ollama_base_url)
    logger.info("  Show Style: %s", settings.show_style)
    logger.info("  Idle Format: %s", settings.idle_format)
    logger.info("  Anchor Voice: %s", settings.anchor_voice_id)
    logger.info("  Analyst Voice: %s", settings.analyst_voice_id)
    logger.info("  Music: %s", "Enabled" if settings.use_music else "Disabled")
    logger.info("  Mock Mode: %s", "Yes" if settings.use_mock_twitter else "No")
    logger.info("  Log Level: %s", settings.log_level)
    logger.info("Press Ctrl+C to stop the station")


def main() -> int:
    """Run station process.

    Returns:
        Process exit code.
    """
    try:
        args = parse_args()
        settings_path = Path(args.config).expanduser()

        if args.init_config:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[logging.StreamHandler(sys.stdout)],
                force=True,
            )
            logger = logging.getLogger(__name__)
            created_settings = create_settings_file(settings_path, overwrite=False)
            example_path = settings_path.parent / config.SETTINGS_EXAMPLE_FILE
            created_example = create_settings_example_file(example_path, overwrite=False)
            if created_settings:
                logger.info("Created runtime settings file at %s", settings_path)
            else:
                logger.info("Runtime settings file already exists at %s", settings_path)
            if created_example:
                logger.info("Created example settings file at %s", example_path)
            else:
                logger.info("Example settings file already exists at %s", example_path)
            return 0

        settings, notes = load_runtime_settings(settings_path)
        cli_overrides = RuntimeCliOverrides(
            force_mock=args.mock,
            disable_music=args.no_music,
            voice_id=args.voice,
            log_level=args.log_level,
        )
        apply_cli_overrides(settings, cli_overrides, notes)
        if args.health_check:
            apply_runtime_settings(settings)
            from modules.healthcheck import health_check_failed, render_health_check_report, run_health_checks

            for note in notes:
                print(f"Settings: {note}")
            results = run_health_checks(settings)
            print(render_health_check_report(results))
            return 1 if health_check_failed(results) else 0
        if args.smoke_test:
            apply_runtime_settings(settings)
            from modules.healthcheck import render_health_check_report
            from modules.smoke_test import run_smoke_test, smoke_test_failed

            for note in notes:
                print(f"Settings: {note}")
            results = run_smoke_test(settings)
            print(render_health_check_report(results))
            return 1 if smoke_test_failed(results) else 0

        if args.gui or not args.no_gui:
            try:
                from desktop_app import run_desktop_app

                return run_desktop_app(settings_path)
            except Exception as exc:
                print(f"Desktop app unavailable ({exc}). Falling back to legacy launcher.")
                from launcher_gui import run_gui

                return run_gui(settings_path)

        apply_runtime_settings(settings)

        setup_logging(settings.log_level)
        logger = logging.getLogger(__name__)

        for note in notes:
            logger.info("Settings: %s", note)

        monitor = get_monitor(use_mock=settings.use_mock_twitter)
        log_banner(logger, settings)

        station = RadioStation(
            monitor=monitor,
            use_music=settings.use_music,
            voice_id=settings.anchor_voice_id,
            anchor_voice_id=settings.anchor_voice_id,
            analyst_voice_id=settings.analyst_voice_id,
        )
        station.start()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger(__name__).exception("Fatal error in main")
        return 1


if __name__ == "__main__":
    sys.exit(main())
