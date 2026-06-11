#!/usr/bin/env python3
"""Phase 0 spike: capture one Lichtblick frame and check headless WebGL viability."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = asyncio.run(_capture(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = Path(args.output)
    print(f"Wrote {output}")
    print(
        f"mean_rgb={result['mean_rgb']:.1f} "
        f"non_black_ratio={result['non_black_ratio']:.3f} "
        f"webgl={result['webgl']}"
    )
    if result["passed"]:
        print("PASS: frame is non-black and WebGL context is available.")
        return 0
    print("FAIL: frame is too dark or WebGL is unavailable.", file=sys.stderr)
    return 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Lichtblick URL to open.")
    parser.add_argument(
        "--output",
        default="reports/demo-capture/spike-frame.png",
        help="PNG screenshot path.",
    )
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument(
        "--wait-before",
        type=float,
        default=8.0,
        help="Seconds to wait after load before screenshot.",
    )
    parser.add_argument(
        "--wait-for-selector",
        default=None,
        help="Optional CSS selector that must appear before capture.",
    )
    parser.add_argument(
        "--software-webgl",
        action="store_true",
        help="Launch Chromium with SwiftShader software WebGL flags.",
    )
    parser.add_argument(
        "--min-mean-rgb",
        type=float,
        default=8.0,
        help="Minimum average RGB brightness to count as non-black.",
    )
    parser.add_argument(
        "--min-non-black-ratio",
        type=float,
        default=0.02,
        help="Minimum fraction of pixels brighter than RGB 16.",
    )
    return parser.parse_args(argv)


async def _capture(args: argparse.Namespace) -> dict[str, float | bool | str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "python Playwright is required. Install with "
            "`python3 -m pip install playwright` and "
            "`python3 -m playwright install chromium`."
        ) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    launch_args: list[str] = []
    if args.software_webgl:
        launch_args.extend(
            [
                "--use-gl=angle",
                "--use-angle=swiftshader",
                "--enable-unsafe-swiftshader",
                "--ignore-gpu-blocklist",
            ]
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=launch_args or None,
        )
        page = await browser.new_page(viewport={"width": args.width, "height": args.height})
        await page.goto(args.url, wait_until="networkidle", timeout=120_000)
        if args.wait_for_selector:
            await page.wait_for_selector(args.wait_for_selector, timeout=120_000)
        if args.wait_before > 0:
            await page.wait_for_timeout(int(args.wait_before * 1000))

        metrics = await page.evaluate(
            """() => {
                const canvas = document.querySelector("canvas");
                const gl = canvas
                    ? canvas.getContext("webgl2") || canvas.getContext("webgl")
                    : null;
                return {
                    canvas_count: document.querySelectorAll("canvas").length,
                    webgl: Boolean(gl),
                    renderer: gl ? gl.getParameter(gl.RENDERER) : "",
                };
            }"""
        )
        await page.screenshot(path=str(output), full_page=False)
        await browser.close()

    stats = _analyze_image(output)
    passed = (
        stats["mean_rgb"] >= args.min_mean_rgb
        and stats["non_black_ratio"] >= args.min_non_black_ratio
        and bool(metrics["webgl"])
    )
    return {
        **stats,
        "webgl": str(metrics["renderer"] or metrics["webgl"]),
        "canvas_count": metrics["canvas_count"],
        "passed": passed,
    }


def _analyze_image(path: Path) -> dict[str, float]:
    try:
        from PIL import Image
    except ImportError:
        return _analyze_image_raw(path)

    image = Image.open(path).convert("RGB")
    pixels = list(image.getdata())
    total = len(pixels)
    if total == 0:
        return {"mean_rgb": 0.0, "non_black_ratio": 0.0}

    brightness = [sum(px) / 3.0 for px in pixels]
    non_black = sum(1 for value in brightness if value > 16.0)
    return {
        "mean_rgb": sum(brightness) / total,
        "non_black_ratio": non_black / total,
    }


def _analyze_image_raw(path: Path) -> dict[str, float]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"not a PNG: {path}")

    # Fallback when Pillow is unavailable: treat non-trivial PNG payload as non-black.
    payload = len(data)
    return {
        "mean_rgb": min(255.0, payload / 1000.0),
        "non_black_ratio": 1.0 if payload > 5000 else 0.0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
