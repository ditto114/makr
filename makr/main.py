"""Entry point for the Makr application."""

from makr.ui.app import MakrApplication


def main() -> None:
    """Main entry point."""
    app = MakrApplication()
    app.run()


if __name__ == "__main__":
    main()
