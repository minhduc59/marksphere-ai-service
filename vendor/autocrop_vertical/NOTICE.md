# Autocrop-vertical — Vendored Copy

**Upstream:** https://github.com/kamilstanuch/Autocrop-vertical
**Pinned commit:** `e02663944597b89b63c7fbfda3ed7166954f5724`
**Commit date:** 2026-02-15
**Retrieved on:** 2026-05-16
**License status:** No `LICENSE` file present upstream as of the pinned commit.

## Why this code lives here

`main.py` is invoked via `subprocess` from
`app/agents/video_clipper/steps/reframe.py` to perform smart 9:16
subject-tracking reframing of highlight clips. It is **not** imported
as a Python module — we call it through the same Python interpreter
that runs the AI service.

## Legal posture

The upstream repository ships no `LICENSE` file. By default this
means all rights are reserved by the author. This vendored copy is
used internally for thesis-defense purposes only. Before any public
or commercial distribution of this project:

1. Contact the upstream author and request an OSI-approved license
   (MIT or Apache-2.0 preferred), **or**
2. Replace this file with an in-house implementation of the same
   algorithm (PySceneDetect + YOLOv8 per-scene detection + OpenCV
   crop + ffmpeg re-encode).

## CLI contract we depend on

```
python3 main.py -i <input.mp4> -o <output.mp4> --ratio 9:16 --quality balanced
```

Exit code 0 on success, non-zero on failure. Output is written to the
path given by `-o`. We capture stdout/stderr for logging.

## Refreshing from upstream

```bash
curl -fsSL https://raw.githubusercontent.com/kamilstanuch/Autocrop-vertical/main/main.py \
     -o ai-service/vendor/autocrop_vertical/main.py
# Update the "Pinned commit" line above to the new SHA.
```
