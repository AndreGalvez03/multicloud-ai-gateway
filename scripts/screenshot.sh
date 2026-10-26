#!/usr/bin/env bash
# Capture docs/images/dashboard.png from the seeded dashboard.
# Uses the compose stack when it is already up. Otherwise starts the API
# on sqlite and the Vite dev server. Does not call a cloud API.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${root}/docs/images"
out="${root}/docs/images/dashboard.png"

api_pid=""
vite_pid=""

cleanup() {
  if [[ -n "${vite_pid}" ]]; then
    kill "${vite_pid}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${api_pid}" ]]; then
    kill "${api_pid}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_http() {
  local url="$1"
  local i=0
  while [[ "${i}" -lt 50 ]]; do
    if curl --silent --fail "${url}" >/dev/null; then
      return 0
    fi
    i=$((i + 1))
    sleep 0.2
  done
  echo "timed out waiting for ${url}" >&2
  return 1
}

if ! curl --silent --fail http://127.0.0.1:8080/healthz >/dev/null; then
  db="/tmp/aigw-screenshot.db"
  rm -f "${db}"
  if [[ -x /tmp/aigw-venv/bin/uvicorn ]]; then
    uvicorn_bin="/tmp/aigw-venv/bin/uvicorn"
  else
    uvicorn_bin="$(command -v uvicorn)"
  fi
  AIGW_DATABASE_URL="sqlite:///${db}" \
    AIGW_SEED_DEMO_DATA=true \
    AIGW_ALLOW_OPEN_READS=true \
    AIGW_ENV=local \
    "${uvicorn_bin}" aigw.api:app --host 127.0.0.1 --port 8080 \
    >/tmp/aigw-screenshot-api.log 2>&1 &
  api_pid=$!
  wait_http http://127.0.0.1:8080/healthz
fi

if ! curl --silent --fail http://127.0.0.1:5173/ >/dev/null; then
  (
    cd "${root}/dashboard"
    npx vite --host 127.0.0.1 --port 5173 >/tmp/aigw-screenshot-vite.log 2>&1
  ) &
  vite_pid=$!
  wait_http http://127.0.0.1:5173/
fi

chrome="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"
rm -rf /tmp/aigw-chrome-profile
# Headless Chrome writes the PNG and then sometimes ignores the exit. Bound it.
set +e
timeout 25 "${chrome}" \
  --headless=new \
  --no-sandbox \
  --disable-gpu \
  --disable-dev-shm-usage \
  --hide-scrollbars \
  --user-data-dir=/tmp/aigw-chrome-profile \
  --window-size=1440,1100 \
  --virtual-time-budget=8000 \
  --screenshot="${out}" \
  http://127.0.0.1:5173/
chrome_status=$?
set -e
if [[ "${chrome_status}" -ne 0 && "${chrome_status}" -ne 124 ]]; then
  echo "chrome exited ${chrome_status}" >&2
  exit "${chrome_status}"
fi

python3 - "${out}" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    from PIL import Image
except ImportError:
    Image = None

if Image is not None:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    background = image.getpixel((8, height - 8))

    def differs(pixel: tuple[int, int, int]) -> bool:
        return any(abs(channel - base) > 14 for channel, base in zip(pixel, background))

    def first(span, axis: str) -> int:
        for index in span:
            if axis == "y":
                hit = any(differs(image.getpixel((x, index))) for x in range(0, width, 3))
            else:
                hit = any(differs(image.getpixel((index, y))) for y in range(0, height, 3))
            if hit:
                return index
        return span[0]

    top = first(range(height), "y")
    bottom = first(range(height - 1, -1, -1), "y")
    left = first(range(width), "x")
    right = first(range(width - 1, -1, -1), "x")
    pad = 24
    image.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(width, right + 1 + pad),
            min(height, bottom + 1 + pad),
        )
    ).save(path, optimize=True)

size = path.stat().st_size
if size < 10000:
    raise SystemExit(f"screenshot looks empty ({size} bytes)")
print(f"wrote {path} ({size} bytes)")
PY
