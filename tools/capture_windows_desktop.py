# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import time

from PIL import ImageGrab


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    time.sleep(max(0.0, float(args.delay)))
    img = ImageGrab.grab()
    img.save(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
