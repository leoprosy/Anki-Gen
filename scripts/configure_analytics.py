"""Generate the public configuration consumed by installers and app.zip."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics_config import write_build_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "analytics_config.json")
    args = parser.parse_args()
    try:
        config = write_build_config(args.output)
    except ValueError as error:
        parser.error(str(error))
    print(f"Analytics configuration: {'configured' if config['project_token'] else 'disabled'}, {config['region']} region.")


if __name__ == "__main__":
    main()
