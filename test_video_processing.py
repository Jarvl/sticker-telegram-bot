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
from pathlib import Path
from typing import Tuple, Optional


DOCKER_IMAGE = "linuxserver/ffmpeg:latest"


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
        # Get dimensions of output file
        return run_ffprobe(output_file)
    except subprocess.CalledProcessError as e:
        print(f"Error running ffmpeg: {e.stderr}")
        raise


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
