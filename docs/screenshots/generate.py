"""Regenerate the terminal screenshots in docs/screenshots/.

Every image is produced by actually running the command it shows, in bash,
from the repository root, and drawing its captured stdout+stderr verbatim.
After each command the same shell runs ``echo $?``, which is drawn as a
second prompt so the exit code shown is the real one. Nothing is typed or
edited by hand; long lines are only soft-wrapped at the window width, the
way a terminal would.

The ``check`` screenshots need a Prometheus. This script serves a stub
Prometheus HTTP API on 127.0.0.1:9090 (the same idea as the test suite's
fixture) that answers each PromQL query with a fixed value per scenario,
and the commands shown point at exactly that address.

Requirements: chaos-kit installed (``pip install -e .``) so ``chaoskit`` is
on PATH, Pillow (``pip install pillow``), and the DejaVu Sans Mono font.

Usage, from the repository root:

    python docs/screenshots/generate.py
"""

from __future__ import annotations

import json
import subprocess
import textwrap
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
PROMETHEUS_HOST, PROMETHEUS_PORT = "127.0.0.1", 9090
PROMETHEUS_URL = f"http://{PROMETHEUS_HOST}:{PROMETHEUS_PORT}"

ERROR_RATE = 'rate(http_requests_total{status=~"5.."}[5m])'
P99_LATENCY = "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))"
CHECKOUT_ERROR_RATE = 'rate(http_requests_total{app="checkout",status=~"5.."}[5m])'

# (file name, command, stub Prometheus values by PromQL query or None)
SHOTS = [
    ("01-validate.png", "chaoskit validate examples/experiment.yaml", None),
    (
        "02-check-pass.png",
        f"chaoskit check examples/experiment.yaml --prometheus {PROMETHEUS_URL}",
        {ERROR_RATE: 0.002, P99_LATENCY: 0.12},
    ),
    (
        "03-check-fail.png",
        f"chaoskit check examples/experiment.yaml --prometheus {PROMETHEUS_URL}",
        {ERROR_RATE: 0.08, P99_LATENCY: 0.12},
    ),
    ("04-help.png", "chaoskit --help", None),
    ("05-validate-cpu-stress.png", "chaoskit validate examples/cpu-stress.yaml", None),
    (
        "06-check-network-latency.png",
        f"chaoskit check examples/network-latency.yaml --prometheus {PROMETHEUS_URL}",
        {CHECKOUT_ERROR_RATE: 0.003},
    ),
]

COLUMNS = 100
FONT_SIZE = 15
PAD_X, PAD_Y, TITLE_H = 20, 18, 34
BG, TITLE_BG, FG, PROMPT = "#0d1117", "#161b22", "#e6edf3", "#58a6ff"
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/Library/Fonts/DejaVuSansMono.ttf",
]


@contextmanager
def stub_prometheus(values: dict[str, float]):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query).get("query", [""])[0]
            if parsed.path != "/api/v1/query" or query not in values:
                self.send_error(404)
                return
            body = json.dumps(
                {
                    "status": "success",
                    "data": {"result": [{"value": [0, str(values[query])]}]},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer((PROMETHEUS_HOST, PROMETHEUS_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run(command: str) -> tuple[list[str], str]:
    """Run ``command`` then ``echo $?`` in one bash; return (output, code)."""
    proc = subprocess.run(
        ["bash", "-c", f"{command}\necho $?"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=True,
    )
    lines = proc.stdout.rstrip("\n").split("\n")
    return lines[:-1], lines[-1]


def wrap(line: str) -> list[str]:
    if not line:
        return [""]
    return textwrap.wrap(
        line,
        COLUMNS,
        drop_whitespace=False,
        replace_whitespace=False,
        break_on_hyphens=False,
    )


def render(path: Path, command: str, output: list[str], code: str) -> None:
    font_path = next((p for p in FONT_PATHS if Path(p).exists()), None)
    if font_path is None:
        raise SystemExit("DejaVu Sans Mono not found; install fonts-dejavu")
    font = ImageFont.truetype(font_path, FONT_SIZE)
    char_w = font.getlength("M")
    line_h = int(FONT_SIZE * 1.5)

    # (prompt?, text) rows: the command, its output, then `echo $?` and code.
    rows = [(True, command)]
    rows += [(False, part) for line in output for part in wrap(line)]
    rows += [(True, "echo $?"), (False, code)]

    width = int(PAD_X * 2 + char_w * (COLUMNS + 2))
    height = TITLE_H + PAD_Y * 2 + line_h * len(rows)
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, TITLE_H], fill=TITLE_BG)
    for i, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        cx, cy = 20 + i * 20, TITLE_H // 2
        draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=color)
    draw.text((90, TITLE_H // 2), "bash", font=font, fill="#8b949e", anchor="lm")

    y = TITLE_H + PAD_Y
    for is_prompt, text in rows:
        x = PAD_X
        if is_prompt:
            draw.text((x, y), "$ ", font=font, fill=PROMPT)
            x += char_w * 2
        draw.text((x, y), text, font=font, fill=FG)
        y += line_h
    img.save(path, optimize=True)


def main() -> None:
    for name, command, values in SHOTS:
        if values is None:
            output, code = run(command)
        else:
            with stub_prometheus(values):
                output, code = run(command)
        render(OUT_DIR / name, command, output, code)
        print(f"{name}: $ {command} -> exit {code}")


if __name__ == "__main__":
    main()
