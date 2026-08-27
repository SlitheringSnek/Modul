# MVS

Hikvision Machine Vision Studio SDK installer for the U3V camera used by [`YOLO/camera_capture.py`](../YOLO/camera_capture.py)
(imports `MvCameraControl_class` from `/opt/MVS/Samples/aarch64/Python/MvImport`).

The installer binaries (`MVS-3.0.1_aarch64_20241128.deb` / `.tar.gz`, ~62MB each) aren't tracked in git —
download the matching version from Hikvision's MVS download page and install it at `/opt/MVS` on the
target Raspberry Pi (aarch64) before running anything under `YOLO/` that touches the camera.
