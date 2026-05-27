# vendor/autocrop_vertical

Vendored copy of [Autocrop-vertical](https://github.com/kamilstanuch/Autocrop-vertical)
— a YOLOv8 + PySceneDetect subject-tracking 9:16 reframer.

See `NOTICE.md` for legal posture and pinned commit info.

## How we use it

The video-clipper agent calls `main.py` as a subprocess (not an import):

```python
subprocess.run(
    [sys.executable, "vendor/autocrop_vertical/main.py",
     "-i", raw_clip_path, "-o", reframed_clip_path,
     "--ratio", "9:16", "--quality", "balanced"],
    capture_output=True, text=True, timeout=300,
)
```

This keeps the dependency footprint of upstream isolated from the rest
of the codebase and lets us swap implementations without touching
caller code.

## Runtime requirements (must be in the AI service image)

- `ffmpeg`, `ffprobe` on `PATH`
- Python packages: `opencv-python-headless`, `scenedetect[opencv]`,
  `ultralytics`, `torch` (CPU build is sufficient), `torchvision`, `tqdm`
- YOLOv8 weights (`yolov8n.pt`) — baked into the Docker image during
  build to avoid cold-start downloads. Ultralytics caches them at
  `~/.config/Ultralytics/yolov8n.pt`.

## Why subprocess, not import?

Upstream `main.py` is a 900-line script with all orchestration inside
`if __name__ == '__main__':`. Refactoring it into an importable module
would diverge from upstream and make refreshes painful. The subprocess
boundary also gives us a clean timeout/kill surface.
