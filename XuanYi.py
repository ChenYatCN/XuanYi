"""Standalone app entrypoint; never imports the main XuanShu application."""
import sys

if __name__ == '__main__':
    if sys.argv[1:] == ['--check-startup']:
        from xuanyi.startup_check import check
        raise SystemExit(check())
    from xuanyi.ui import launch
    raise SystemExit(launch())
