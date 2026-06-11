#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        asyncio.run(_record(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record a real browser-based Nav2 demo, such as Foxglove Studio, "
            "to an animated GIF using Playwright screenshots and ffmpeg."
        )
    )
    parser.add_argument("--url", required=True, help="Browser URL to record.")
    parser.add_argument(
        "--output",
        default="docs/assets/nav2-scenario-runner-demo.gif",
        help="Output GIF path.",
    )
    parser.add_argument("--duration", type=float, default=12.0, help="Recording duration in seconds.")
    parser.add_argument("--fps", type=int, default=8, help="Frames per second.")
    parser.add_argument("--width", type=int, default=1440, help="Browser viewport width.")
    parser.add_argument("--height", type=int, default=900, help="Browser viewport height.")
    parser.add_argument(
        "--crop-left",
        type=int,
        default=0,
        help="Pixels to crop from the left edge before GIF scaling.",
    )
    parser.add_argument(
        "--wait-before",
        type=float,
        default=2.0,
        help="Seconds to wait after page load before recording.",
    )
    parser.add_argument(
        "--wait-for-selector",
        default=None,
        help="Optional CSS selector that must appear before recording starts.",
    )
    parser.add_argument(
        "--click",
        action="append",
        default=[],
        metavar="X,Y",
        help="Viewport coordinate to click after loading and before recording. May be repeated.",
    )
    parser.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default="chromium",
        help="Playwright browser engine.",
    )
    parser.add_argument(
        "--software-webgl",
        action="store_true",
        help=(
            "Launch Chromium with SwiftShader software WebGL flags for headless "
            "3D panel capture."
        ),
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="Keep captured PNG frames beside the GIF for debugging.",
    )
    return parser.parse_args(argv)


async def _record(args: argparse.Namespace) -> None:
    if args.duration <= 0:
        raise ValueError("--duration must be positive.")
    if args.fps <= 0:
        raise ValueError("--fps must be positive.")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required on PATH.")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "python Playwright is required. Install it with `python3 -m pip install playwright` "
            "and install a browser with `python3 -m playwright install chromium`."
        ) from exc

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(args.duration * args.fps))

    if args.keep_frames:
        frame_dir = output.with_suffix("")
        frame_dir.mkdir(parents=True, exist_ok=True)
        cleanup = None
    else:
        cleanup = tempfile.TemporaryDirectory(prefix="nav2_scenario_runner_demo_")
        frame_dir = Path(cleanup.name)

    try:
        async with async_playwright() as playwright:
            browser_launcher = getattr(playwright, args.browser)
            launch_kwargs: dict = {"headless": True}
            if args.software_webgl:
                if args.browser != "chromium":
                    raise ValueError("--software-webgl requires --browser chromium.")
                launch_kwargs["args"] = [
                    "--use-gl=angle",
                    "--use-angle=swiftshader",
                    "--enable-unsafe-swiftshader",
                    "--ignore-gpu-blocklist",
                ]
            browser = await browser_launcher.launch(**launch_kwargs)
            page = await browser.new_page(viewport={"width": args.width, "height": args.height})
            await page.goto(args.url, wait_until="networkidle")
            if args.wait_for_selector:
                await page.wait_for_selector(args.wait_for_selector, timeout=30000)
            for click in args.click:
                x_text, y_text = click.split(",", maxsplit=1)
                await page.mouse.click(float(x_text), float(y_text))
            if args.wait_before > 0:
                await page.wait_for_timeout(int(args.wait_before * 1000))

            for index in range(frame_count):
                await page.screenshot(path=str(frame_dir / f"frame_{index:05d}.png"))
                if index < frame_count - 1:
                    await page.wait_for_timeout(int(1000 / args.fps))
            await browser.close()

        _encode_gif(frame_dir=frame_dir, output=output, fps=args.fps, crop_left=args.crop_left)
    finally:
        if cleanup is not None:
            cleanup.cleanup()


def _encode_gif(frame_dir: Path, output: Path, fps: int, crop_left: int = 0) -> None:
    input_pattern = str(frame_dir / "frame_%05d.png")
    palette = frame_dir / "palette.png"
    if crop_left < 0:
        raise ValueError("--crop-left must be non-negative.")
    crop_filter = f"crop=iw-{crop_left}:ih:{crop_left}:0," if crop_left else ""
    palette_filter = f"fps={fps},{crop_filter}scale=960:-1:flags=lanczos,palettegen"
    gif_filter = f"fps={fps},{crop_filter}scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            input_pattern,
            "-vf",
            palette_filter,
            str(palette),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            input_pattern,
            "-i",
            str(palette),
            "-lavfi",
            gif_filter,
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    raise SystemExit(main())
