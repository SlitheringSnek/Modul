# MVS

Hikvision Machine Vision Studio SDK installer for the U3V camera used by [`YOLO/camera_capture.py`](../YOLO/camera_capture.py)
(imports `MvCameraControl_class` from `/opt/MVS/Samples/aarch64/Python/MvImport`).

The installer binaries (`MVS-3.0.1_aarch64_20241128.deb` / `.tar.gz`, ~62MB each) aren't tracked in git —
download the matching version from Hikvision's MVS download page and install it at `/opt/MVS` on the
target Raspberry Pi (aarch64) before running anything under `YOLO/` that touches the camera.

## Required post-install step: `/opt/MVS/aarch64` symlink

`MvCameraControl_class.py` (part of the SDK, at `/opt/MVS/Samples/aarch64/Python/MvImport/`) loads the
native library from `$MVCAM_COMMON_RUNENV/aarch64/libMvCameraControl.so`, which resolves to
`/opt/MVS/aarch64/libMvCameraControl.so` (`main.py` hardcodes `MVCAM_COMMON_RUNENV=/opt/MVS`). On every
Pi we've set up so far, the `.deb` actually installs the library under `/opt/MVS/lib/aarch64/` instead —
`/opt/MVS/aarch64/` doesn't exist, so the import fails with:

```
OSError: /opt/MVS/aarch64/libMvCameraControl.so: cannot open shared object file: No such file or directory
```

Fix (one-time, per Pi, after installing the `.deb`):

```bash
sudo ln -s /opt/MVS/lib/aarch64 /opt/MVS/aarch64
```

This is a filesystem-level symlink, not an environment variable, so — unlike `ROBOFLOW_API_KEY` — it
works identically whether the code is run directly in a terminal or triggered non-interactively (e.g. by
Node-RED's `exec` node). No corresponding `~/.bashrc`-style gotcha here.
