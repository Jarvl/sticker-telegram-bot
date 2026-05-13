#!/usr/bin/env python3
"""
Video Processing Debug Script

Tests the video processing pipeline step-by-step using Docker-based ffmpeg.
Identifies where dimensions become incorrect in the filter chain.

Usage:
    python test_video_processing.py path/to/test.gif
"""

import subprocess
import sys
import os
import re
import hashlib
import json
import time
from pathlib import Path
from typing import Tuple, Optional


DOCKER_IMAGE = "linuxserver/ffmpeg:latest"


# region agent log
def agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict):
    payload = {
        "sessionId": "f2b8d8",
        "runId": "initial",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(
            "/Users/andrew/Projects/sticker-telegram-bot/.cursor/debug-f2b8d8.log",
            "a",
            encoding="utf-8",
        ) as debug_file:
            debug_file.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


def mp4_boxes(data: bytes, limit: int = 12):
    boxes = []
    offset = 0
    data_len = len(data)
    while offset + 8 <= data_len and len(boxes) < limit:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8].decode("latin-1", errors="replace")
        header_size = 8
        if size == 1 and offset + 16 <= data_len:
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = data_len - offset
        if size < header_size:
            boxes.append({"offset": offset, "type": box_type, "size": size, "invalid": True})
            break
        boxes.append({"offset": offset, "type": box_type, "size": size})
        offset += size
    return boxes
# endregion


def run_ffprobe(file_path: str) -> Tuple[int, int]:
    """
    Get video dimensions using ffprobe in Docker.

    Returns:
        Tuple of (width, height)
    """
    abs_path = os.path.abspath(file_path)
    work_dir = os.path.dirname(abs_path)
    filename = os.path.basename(abs_path)

    # Use ffprobe with explicit output format
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work_dir}:/work",
        "-w", "/work",
        "--entrypoint", "ffprobe",
        DOCKER_IMAGE,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        filename
    ]

    try:
        # ffprobe outputs to stdout with this format
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()

        # Output format will be: "width,height"
        if ',' in output:
            width, height = output.split(',')
            return int(width), int(height)
        else:
            raise ValueError(f"Unexpected ffprobe output format: {output}")
    except subprocess.CalledProcessError as e:
        print(f"Error running ffprobe: {e.stderr}")
        raise
    except ValueError as e:
        print(f"Error parsing dimensions: {e}")
        raise


def run_ffmpeg(input_file: str, filter_chain: str, output_file: str, full_pipeline: bool = False) -> Tuple[int, int]:
    """
    Run ffmpeg in Docker with specified filter chain.

    Args:
        input_file: Path to input file
        filter_chain: ffmpeg filter string
        output_file: Path to output file
        full_pipeline: If True, apply full VP9 encoding pipeline

    Returns:
        Tuple of (width, height) of output video
    """
    abs_input = os.path.abspath(input_file)
    abs_output = os.path.abspath(output_file)

    # Get directories
    input_dir = os.path.dirname(abs_input)
    output_dir = os.path.dirname(abs_output)

    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Get current working directory for mounting
    cwd = os.getcwd()

    # Mount both input directory and current working directory
    # Note: linuxserver/ffmpeg image has ffmpeg as entrypoint, so we don't specify it again
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{input_dir}:/input",
        "-v", f"{cwd}:/work",
        "-w", "/work",
        DOCKER_IMAGE,
        "-i", f"/input/{os.path.basename(abs_input)}",
        "-vf", filter_chain,
    ]

    if full_pipeline:
        # Add full VP9 encoding options
        cmd.extend([
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",  # Required for alpha transparency
            "-crf", "30",
            "-b:v", "0",
            "-deadline", "good",
            "-cpu-used", "4",
            "-an",
        ])
    else:
        # Simple encoding for intermediate steps
        cmd.extend([
            "-c:v", "libvpx-vp9",
            "-pix_fmt", "yuva420p",  # Required for alpha transparency
            "-crf", "30",
            "-b:v", "0",
            "-an",
        ])

    # Output path relative to /work
    output_rel = os.path.relpath(abs_output, cwd)
    cmd.append(output_rel)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if full_pipeline:
            agent_debug_log(
                "H1",
                "test_video_processing.py:run_ffmpeg:file_exit",
                "file-mode ffmpeg exited",
                {
                    "input_file": input_file,
                    "output_file": output_file,
                    "returncode": result.returncode,
                    "stderr_size": len(result.stderr),
                    "filter_chain": filter_chain,
                    "input_mode": "seekable_file",
                },
            )
        # Get dimensions of output file
        return run_ffprobe(output_file)
    except subprocess.CalledProcessError as e:
        if full_pipeline:
            agent_debug_log(
                "H1",
                "test_video_processing.py:run_ffmpeg:file_exit",
                "file-mode ffmpeg failed",
                {
                    "input_file": input_file,
                    "output_file": output_file,
                    "returncode": e.returncode,
                    "stderr_size": len(e.stderr),
                    "stderr_tail": e.stderr[-2000:],
                    "filter_chain": filter_chain,
                    "input_mode": "seekable_file",
                },
            )
        print(f"Error running ffmpeg: {e.stderr}")
        raise


def run_ffmpeg_pipe(input_file: str, filter_chain: str, full_pipeline: bool = False) -> dict:
    """
    Run ffmpeg with the same non-seekable stdin/stdout pattern used by the bot.
    """
    abs_input = os.path.abspath(input_file)
    input_data = Path(abs_input).read_bytes()
    agent_debug_log(
        "H1,H2,H5",
        "test_video_processing.py:run_ffmpeg_pipe:input",
        "pipe-mode input prepared",
        {
            "input_file": input_file,
            "input_size": len(input_data),
            "sha256_16": hashlib.sha256(input_data).hexdigest()[:16],
            "prefix_hex": input_data[:16].hex(),
            "suffix_hex": input_data[-16:].hex(),
            "mp4_boxes": mp4_boxes(input_data),
            "filter_chain": filter_chain,
            "full_pipeline": full_pipeline,
        },
    )

    cmd = [
        "docker", "run", "--rm", "-i",
        DOCKER_IMAGE,
        "-i", "pipe:0",
        "-vf", filter_chain,
        "-c:v", "libvpx-vp9",
        "-crf", "30",
        "-b:v", "0",
    ]
    if full_pipeline:
        cmd.extend(["-deadline", "good", "-cpu-used", "4"])
    cmd.extend(["-an", "-f", "webm", "pipe:1"])

    result = subprocess.run(cmd, input=input_data, capture_output=True)
    stderr_text = result.stderr.decode("utf-8", errors="ignore")
    agent_debug_log(
        "H1,H3,H4,H5",
        "test_video_processing.py:run_ffmpeg_pipe:exit",
        "pipe-mode ffmpeg exited",
        {
            "returncode": result.returncode,
            "stdout_size": len(result.stdout),
            "stderr_size": len(result.stderr),
            "partial_file": "partial file" in stderr_text.lower(),
            "invalid_data": "invalid data" in stderr_text.lower(),
            "unspecified_pixel_format": "unspecified pixel format" in stderr_text.lower(),
            "could_not_find_codec_parameters": (
                "could not find codec parameters" in stderr_text.lower()
            ),
            "stderr_tail": stderr_text[-2000:],
        },
    )
    return {
        "returncode": result.returncode,
        "stdout_size": len(result.stdout),
        "stderr": stderr_text,
    }


def calculate_expected_scale(width: int, height: int) -> Tuple[int, int]:
    """
    Calculate expected dimensions after scaling to 512px on longest side.

    FFmpeg rounds dimensions to ensure they're even (required for many codecs).

    Args:
        width: Input width
        height: Input height

    Returns:
        Tuple of (expected_width, expected_height)
    """
    if width > height:
        # Landscape: width becomes 512
        ratio = 512 / width
        # Round to nearest even number
        new_height = round(height * ratio / 2) * 2
        return (512, new_height)
    elif height > width:
        # Portrait: height becomes 512
        ratio = 512 / height
        # Round to nearest even number
        new_width = round(width * ratio / 2) * 2
        return (new_width, 512)
    else:
        # Square
        return (512, 512)


def get_aspect_ratio_type(width: int, height: int) -> str:
    """Get human-readable aspect ratio type."""
    if width > height:
        return "landscape"
    elif height > width:
        return "portrait"
    else:
        return "square"


def test_video_processing(input_file: str) -> dict:
    """
    Run complete test pipeline and return results.

    Args:
        input_file: Path to input video/GIF file

    Returns:
        Dictionary with test results
    """
    # Create output directory
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)

    results = {
        "input_file": input_file,
        "steps": [],
        "overall_pass": True
    }

    print(f"Testing video processing: {input_file}")
    print("=" * 60)
    print()

    # Step 0: Bot-style pipe input
    print("Step 0: Bot-style pipe input")
    print("  Input: pipe:0 / Output: pipe:1")
    try:
        pipe_result = run_ffmpeg_pipe(
            input_file,
            "setpts=PTS/2.1999999999999997,scale=512:512:force_original_aspect_ratio=decrease,pad=512:512:(ow-iw)/2:(oh-ih)/2:color=black,fps=30",
            full_pipeline=True,
        )
        pipe_pass = pipe_result["returncode"] == 0 and pipe_result["stdout_size"] > 0
        print(f"  Return code: {pipe_result['returncode']}")
        print(f"  Output bytes: {pipe_result['stdout_size']}")
        print(f"  Status: {'✅ PASS' if pipe_pass else '❌ FAIL'}")
        if not pipe_pass:
            print(f"  Error tail: {pipe_result['stderr'][-1200:]}")
            results["overall_pass"] = False
        results["steps"].append({
            "name": "Bot pipe",
            "expected": "non-empty webm output",
            "actual": (pipe_result["returncode"], pipe_result["stdout_size"]),
            "pass": pipe_pass
        })
    except Exception as e:
        print(f"  Error: {e}")
        print("  Status: ❌ FAIL")
        results["overall_pass"] = False

    print()

    # Get input dimensions
    try:
        input_width, input_height = run_ffprobe(input_file)
        aspect_type = get_aspect_ratio_type(input_width, input_height)
        print(f"Input dimensions: {input_width}x{input_height} ({aspect_type})")
        print()
    except Exception as e:
        print(f"Failed to read input file: {e}")
        results["overall_pass"] = False
        return results

    # Calculate expected dimensions after scale
    expected_scaled_w, expected_scaled_h = calculate_expected_scale(input_width, input_height)

    # Step 1: Scale only
    print("Step 1: Scale")
    print("  Filter: scale=512:512:force_original_aspect_ratio=decrease")
    print(f"  Expected: {expected_scaled_w}x{expected_scaled_h}")

    try:
        actual_w, actual_h = run_ffmpeg(
            input_file,
            "scale=512:512:force_original_aspect_ratio=decrease",
            str(output_dir / "step1_scale.webm")
        )
        print(f"  Actual: {actual_w}x{actual_h}")

        step1_pass = (actual_w == expected_scaled_w and actual_h == expected_scaled_h)
        print(f"  Status: {'✅ PASS' if step1_pass else '❌ FAIL'}")

        results["steps"].append({
            "name": "Scale",
            "expected": (expected_scaled_w, expected_scaled_h),
            "actual": (actual_w, actual_h),
            "pass": step1_pass
        })

        if not step1_pass:
            results["overall_pass"] = False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Status: ❌ FAIL")
        results["overall_pass"] = False

    print()

    # Step 2: Scale + Format
    print("Step 2: Format")
    print("  Filter: scale + format=yuva420p")
    print(f"  Expected: {expected_scaled_w}x{expected_scaled_h} (no change)")

    try:
        actual_w, actual_h = run_ffmpeg(
            input_file,
            "scale=512:512:force_original_aspect_ratio=decrease,format=yuva420p",
            str(output_dir / "step2_format.webm")
        )
        print(f"  Actual: {actual_w}x{actual_h}")

        step2_pass = (actual_w == expected_scaled_w and actual_h == expected_scaled_h)
        print(f"  Status: {'✅ PASS' if step2_pass else '❌ FAIL'}")

        results["steps"].append({
            "name": "Format",
            "expected": (expected_scaled_w, expected_scaled_h),
            "actual": (actual_w, actual_h),
            "pass": step2_pass
        })

        if not step2_pass:
            results["overall_pass"] = False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Status: ❌ FAIL")
        results["overall_pass"] = False

    print()

    # Step 3: Scale + Format + Pad
    print("Step 3: Pad")
    print("  Filter: scale + format + pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000")
    print("  Expected: 512x512")

    try:
        actual_w, actual_h = run_ffmpeg(
            input_file,
            "scale=512:512:force_original_aspect_ratio=decrease,format=yuva420p,pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000",
            str(output_dir / "step3_pad.webm")
        )
        print(f"  Actual: {actual_w}x{actual_h}")

        step3_pass = (actual_w == 512 and actual_h == 512)
        print(f"  Status: {'✅ PASS' if step3_pass else '❌ FAIL'}")

        results["steps"].append({
            "name": "Pad",
            "expected": (512, 512),
            "actual": (actual_w, actual_h),
            "pass": step3_pass
        })

        if not step3_pass:
            results["overall_pass"] = False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Status: ❌ FAIL")
        results["overall_pass"] = False

    print()

    # Step 4: Full pipeline (with FPS)
    print("Step 4: FPS + Full Encoding")
    print("  Filter: full pipeline with fps=30 + VP9 encoding")
    print("  Expected: 512x512")

    try:
        actual_w, actual_h = run_ffmpeg(
            input_file,
            "scale=512:512:force_original_aspect_ratio=decrease,format=yuva420p,pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000,fps=30",
            str(output_dir / "final.webm"),
            full_pipeline=True
        )
        print(f"  Actual: {actual_w}x{actual_h}")

        step4_pass = (actual_w == 512 and actual_h == 512)
        print(f"  Status: {'✅ PASS' if step4_pass else '❌ FAIL'}")

        results["steps"].append({
            "name": "Final",
            "expected": (512, 512),
            "actual": (actual_w, actual_h),
            "pass": step4_pass
        })

        if not step4_pass:
            results["overall_pass"] = False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Status: ❌ FAIL")
        results["overall_pass"] = False

    print()
    print("=" * 60)
    print(f"Final result: {'✅ ALL TESTS PASSED' if results['overall_pass'] else '❌ SOME TESTS FAILED'}")
    print(f"Output files saved to: {output_dir}/")
    print()

    return results


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python test_video_processing.py path/to/test.gif")
        sys.exit(1)

    input_file = sys.argv[1]

    if not os.path.exists(input_file):
        print(f"Error: File not found: {input_file}")
        sys.exit(1)

    try:
        results = test_video_processing(input_file)
        sys.exit(0 if results["overall_pass"] else 1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
