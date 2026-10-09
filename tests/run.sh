#!/bin/sh
# Run the test suite: tests/run.sh [unittest args, e.g. tests.test_app.AppTest.test_move_then_restore]
# Uses a Python that has tkinter and, when there's no display, a virtual one from xvfb-run.
cd "$(dirname "$0")/.." || exit 1
PY=""
for p in "${PYTHON:-}" python3 /usr/bin/python3 /usr/bin/python3.12 /usr/bin/python3.11; do
    [ -n "$p" ] && command -v "$p" >/dev/null 2>&1 && "$p" -c "import tkinter" 2>/dev/null && PY=$p && break
done
[ -n "$PY" ] || { echo "No Python with tkinter (Debian / Ubuntu: sudo apt install python3-tk)" >&2; exit 1; }
[ $# -gt 0 ] || set -- discover -s tests -t .
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then
    exec xvfb-run -a -s "-screen 0 1600x1000x24" "$PY" -m unittest "$@"
fi
exec "$PY" -m unittest "$@"
