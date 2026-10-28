"""Build the native C library and launch the loopback web application."""
import subprocess
import sys
from build import ROOT, build as build_project

# Kept for the offline repair tool and existing callers.
def build():
    return build_project('web')


def main():
    try:
        build()
        from server import main as serve
        return serve()
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print(f'Launch failed: {error}',file=sys.stderr);return 1
    except KeyboardInterrupt:
        return 0


if __name__=='__main__':raise SystemExit(main())
