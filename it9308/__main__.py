import sys

from .cli import main

if __name__ == "__main__":
    # A CLI promise, not a style choice: a user who is missing a DLL or an image gets one line, never a
    # traceback (HEAD's B11). Anything unexpected still exits non-zero.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        raise SystemExit(130)
    except BaseException as error:  # noqa: BLE001 - the last line of defence for a user-facing CLI
        print("error: %s" % error, file=sys.stderr)
        raise SystemExit(1)
