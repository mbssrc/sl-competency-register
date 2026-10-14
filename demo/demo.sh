#!/usr/bin/env bash
# Spin up a complete, populated demo instance of the personnel tool.
#
# Creates a throwaway database in .demo-run/, seeds the committed demo
# population into it, verifies the result, and serves it. The real database in
# web/ is never opened.
set -euo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$DEMO_DIR")"
RUN_DIR="$REPO_ROOT/.demo-run"
WEB_DIR="$REPO_ROOT/web"

PORT=8000
KEEP=0
BUILD_CSS=1
SERVE=1

usage() {
    cat <<USAGE
Usage: demo/demo.sh [options]

  --port N     Serve on port N instead of $PORT.
  --keep       Keep an existing .demo-run database instead of rebuilding it.
  --no-css     Skip the stylesheet and asset build.
  --no-serve   Set everything up and verify it, but do not start the server.
  -h, --help   Show this message.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="${2:?--port needs a number}"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --no-css) BUILD_CSS=0; shift ;;
        --no-serve) SERVE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "demo.sh: unknown option '$1'" >&2; usage >&2; exit 2 ;;
    esac
done

die() { echo "demo.sh: $*" >&2; exit 1; }

if ! python3 -c 'import django' >/dev/null 2>&1; then
    die "Django is not importable. Run 'nix develop' first, or install the web
         dependencies listed in README.md, then run this script again."
fi

# Everything the app writes goes here, which is why web/'s databases are safe.
export PERSONNEL_DATA_DIR="$RUN_DIR"
export PERSONNEL_TAXONOMY_DIR="$REPO_ROOT"
export DJANGO_DEBUG=true
export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1"

if [ "$KEEP" -eq 0 ]; then
    rm -rf "$RUN_DIR"
fi
mkdir -p "$RUN_DIR"

SEEDED=0
if [ "$KEEP" -eq 1 ] && [ -f "$RUN_DIR/personnel.sqlite3" ]; then
    echo "==> Keeping the existing demo database in .demo-run/"
    SEEDED=1
fi

echo "==> Checking the demo data"
python3 "$DEMO_DIR/validate.py"

# Always rebuild. The build also copies static/src/background.png into
# static/dist/, so a "only if output.css is missing" check would silently serve
# a stale stylesheet and a stale background after any edit to the sources. It
# takes under a second, which is cheaper than being wrong.
if [ "$BUILD_CSS" -eq 1 ]; then
    if command -v npm >/dev/null 2>&1; then
        echo "==> Building the stylesheet and static assets"
        [ -d "$WEB_DIR/node_modules" ] || ( cd "$WEB_DIR" && npm install --silent )
        ( cd "$WEB_DIR" && npm run build --silent )
    elif [ -f "$WEB_DIR/static/dist/output.css" ]; then
        echo "==> npm is not available; using the existing compiled assets," \
             "which may be out of date"
    else
        die "no compiled stylesheet and npm is not available. Run 'nix develop',
             or pass --no-css to serve an unstyled page."
    fi
elif [ ! -f "$WEB_DIR/static/dist/output.css" ]; then
    echo "==> No compiled stylesheet and --no-css was passed: the page will be unstyled"
fi

if [ "$SEEDED" -eq 0 ]; then
    echo "==> Creating the databases"
    python3 "$WEB_DIR/manage.py" migrate --no-input
    python3 "$WEB_DIR/manage.py" migrate taxonomy --database taxonomy --no-input

    echo "==> Loading the taxonomy"
    python3 "$WEB_DIR/manage.py" seed_taxonomy

    echo "==> Seeding the demo population"
    python3 "$DEMO_DIR/seed.py"
fi

echo "==> Verifying"
python3 "$DEMO_DIR/verify.py"

cat <<BANNER

  The demo is ready at http://127.0.0.1:$PORT/

    admin / admin        full access
    manager / manager    all personnel, assessments, projects and reports
    user / user          own record only (linked to the new hire)

  Start at the dashboard, then Reports -> Gap Analysis.
  demo/README.md has a walkthrough and explains what the data shows.

BANNER

if [ "$SERVE" -eq 1 ]; then
    exec python3 "$WEB_DIR/manage.py" runserver "$PORT"
fi
