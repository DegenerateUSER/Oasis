"""Native executable entry point, including the private GUI worker dispatch."""
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # A compiled executable cannot interpret Python's ``-m`` worker command.
    # Keep this private, exact-arity route separate from the public CLI parser.
    if len(argv) == 2 and argv[0] == '--_oasis-gui-worker':
        import logging
        from pathlib import Path

        from tfmutate.gui.worker import run

        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        run(Path(argv[1]))
        return 0

    from tfmutate.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
