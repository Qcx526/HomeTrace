"""Run after installing HomeTrace: python tools/build_submission.py --config ..."""

from hometrace.submission import main


if __name__ == "__main__":
    raise SystemExit(main())
