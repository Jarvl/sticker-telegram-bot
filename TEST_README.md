# Video Processing Test Script

This script helps debug the animated sticker video processing pipeline by testing each filter step independently.

## Prerequisites

- **Docker installed and running** (that's it!)
- No local ffmpeg installation needed

The script automatically uses the `jrottenberg/ffmpeg:4.4-alpine` Docker image.

## Usage

```bash
python test_video_processing.py path/to/your/test.gif
```

## What It Does

The script processes your video through each filter step and shows:

1. **Input dimensions** - Your original video size
2. **Step 1: Scale** - After scaling to 512px on longest side
3. **Step 2: Format** - After adding alpha channel (yuva420p)
4. **Step 3: Pad** - After padding to 512x512 with transparency
5. **Step 4: Final** - After adding 30fps and full VP9 encoding

For each step, it shows:
- Expected dimensions
- Actual dimensions
- ✅ PASS or ❌ FAIL status

## Output

All intermediate files are saved to `test_output/`:
- `step1_scale.webm` - After scale filter
- `step2_format.webm` - After format filter
- `step3_pad.webm` - After pad filter
- `final.webm` - Complete pipeline output

## Example Output

```
Testing video processing: test.gif
============================================================

Input dimensions: 800x600 (landscape)

Step 1: Scale
  Filter: scale=512:512:force_original_aspect_ratio=decrease
  Expected: 512x384
  Actual: 512x384
  Status: ✅ PASS

Step 2: Format
  Filter: scale + format=yuva420p
  Expected: 512x384 (no change)
  Actual: 512x384
  Status: ✅ PASS

Step 3: Pad
  Filter: scale + format + pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000
  Expected: 512x512
  Actual: 512x512
  Status: ✅ PASS

Step 4: FPS + Full Encoding
  Filter: full pipeline with fps=30 + VP9 encoding
  Expected: 512x512
  Actual: 512x512
  Status: ✅ PASS

============================================================
Final result: ✅ ALL TESTS PASSED
Output files saved to: test_output/
```

## Test Cases

Try testing with different aspect ratios:

1. **Landscape** (e.g., 800x600) → should scale to 512x384 → pad to 512x512
2. **Portrait** (e.g., 600x800) → should scale to 384x512 → pad to 512x512
3. **Square** (e.g., 500x500) → should scale to 512x512 → no padding needed
4. **Wide** (e.g., 1000x200) → should scale to 512x102 → pad to 512x512
5. **Tall** (e.g., 200x1000) → should scale to 102x512 → pad to 512x512

## Troubleshooting

### Docker image pull
If this is your first time running the script, Docker will automatically pull the ffmpeg image. This may take a minute.

### Permission errors
If you get permission errors:
```bash
chmod +x test_video_processing.py
```

### File not found
Make sure to provide the correct path to your test video:
```bash
# Relative path
python test_video_processing.py ./test_files/animation.gif

# Absolute path
python test_video_processing.py /Users/you/Downloads/test.gif
```

## Debugging

If a step fails, the script will show you:
1. **Which step failed** - Is it scale, format, pad, or final encoding?
2. **Expected vs actual** - What dimensions were expected vs what you got
3. **Output files** - Check the intermediate files in `test_output/` to visually inspect

This helps pinpoint exactly where in the pipeline the issue occurs.
