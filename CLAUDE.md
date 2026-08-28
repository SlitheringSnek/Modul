# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Control software for a Raspberry Pi–based robotic assembly module ("Modul") that uses a Dobot Magician
arm, a conveyor belt, and a Hikvision machine-vision camera to detect toy-train components (by color and
part type), transform detected pixel coordinates into robot coordinates, and drive pick-and-place assembly
sequences. It's one station in a larger modular manufacturing line coordinated externally by Node-RED and
an AGV, exchanging state through plain JSON/text files on disk (see "Cross-process data files" below)
rather than an in-process API.

There are three top-level areas:

- **`YOLO/`** — the vision pipeline: captures an image, runs YOLO-based object detection locally in-process
  via the Roboflow `inference` SDK (a Roboflow-trained model, downloaded/cached on first run, no Docker),
  computes robot pick coordinates via a camera→robot homography, and writes those coordinates into the
  shared movement-data file. Runs on the Pi that has the camera attached.
- **`FW_DOBOT/`** — Dobot control: vendored copies of the `pydobot` and `pydobotplus` driver libraries
  (`pydobot-master/`, `pydobotplus-master/`, each a full upstream checkout with its own `setup.py`), plus
  `modularAssembly/`, the actual production scripts that read the shared JSON files and drive the arm and
  conveyor belt through a hand-rolled `lib/` protocol implementation.
- **`MVS/`** — the Hikvision Machine Vision Studio SDK installer (`.deb` / `.tar.gz`), a binary dependency
  installed system-wide (typically at `/opt/MVS`), not source code to edit.

There is no build system, package manifest, or test suite — this is a collection of scripts meant to be
run directly on the target Raspberry Pi hardware with real (or simulated) Dobot/camera hardware attached.
There's nothing to build or lint; verifying a change means reading the code path carefully or running it
against real/mock hardware.

## Setup and running

Environment setup, calibration walkthrough, and the YOLO workflow are documented narratively in
[`YOLO/README.txt`](YOLO/README.txt) (mixed Slovene/English) — read it before changing the detection
pipeline or calibration flow. Rough shape:

```bash
# one-time: pyenv + a Python 3.10 venv (see YOLO/README.txt for full pyenv bootstrap)
pyenv virtualenv 3.10 train-detector-venv
pyenv activate train-detector-venv
pip install -r YOLO/requirements.txt   # minimal set: numpy, opencv-python, pydobot, pydobotplus,
                                        # pyserial, inference (the Roboflow local-inference SDK)

python YOLO/main.py                    # capture + detect (locally, in-process) + update movement_data
```

There's a second, much larger `requirements.txt` at the repo root — a full `pip freeze` of a known-working
Raspberry Pi's system Python, kept only for reference/exact-parity cases. **Don't use it for normal
setup on a new Pi** — in practice it reliably fails partway through on OS-tied packages that need apt dev
headers to build from source (`dbus-python` needs `libdbus-1-dev`, `PyGObject` needs `libgirepository`,
etc.), wasting real time for no benefit, since the project doesn't import any of them. `YOLO/requirements.txt`
(the six packages above) is the one to actually install on every Pi.

First run of `main.py`/`main_calibration.py` needs internet + a valid `api_key` in `DEFAULT_CONFIG` to
download and cache the Roboflow-trained model weights (via `get_model()` in `component_detector.py`);
later runs load the cached weights and can run fully offline. There is no Docker dependency and no
`start_docker.py`/`stop_docker.py` anymore — those were removed when the inference server was replaced
with in-process local inference.

`FW_DOBOT/modularAssembly/*.py` (e.g. `assembly_NR.py`, `conveyor_with_IR.py`,
`conveyor_prepare_for_assembly.py`) are run standalone on the Pi to actually move the arm/conveyor; they
assume the shared data files below already exist at their hardcoded paths.

## Architecture: how the pieces actually connect

**Detection and robot execution are deliberately decoupled and run as separate processes/scripts**,
coordinated only through files on disk — there is no direct function call or IPC between `YOLO/main.py`
and the `FW_DOBOT/modularAssembly` scripts:

1. `YOLO/main.py` orchestrates: capture an image (`camera_capture.py`, via the Hikvision SDK) → run
   detection (`component_detector.py`, calling `model.infer()` on a Roboflow model loaded locally
   in-process via `inference.get_model()` — no server, no network call per-frame) → draw/save results
   (`component_visualizer.py`) → load the homography matrix and **rewrite**
   `FW_DOBOT/modularAssembly/movement_data` in place with the detected pick-up X/Y for each component
   (`robot_manager.py`). It never moves the robot arm itself in normal operation — `calibration_mode` is
   the one exception, where it drives the Dobot directly to build the homography.
2. `FW_DOBOT/modularAssembly/assembly_NR.py` (run separately, e.g. triggered by Node-RED) reads
   `order_data` (what part/color to assemble, written externally by Node-RED) and the now-updated
   `movement_data`, looks up the matching move sequence, and drives the Dobot through it via `pydobotplus`.

**Cross-process data files** (paths are hardcoded absolute paths like `/home/pi/Desktop/...` throughout —
grep for them when relocating the project):
- `FW_DOBOT/modularAssembly/movement_data` — JSON keyed by part type (e.g. `trainEngine`, `trainCabin`,
  `trainBase`/`trainWheels`), each mapping to 4 move-sequence arrays (index = color: red, green, blue,
  yellow per the `color_map` convention repeated in `robot_manager.py`, `assembly_NR.py`, and
  `calibrate_robot.py`). Each move is `[x, y, z, r, suck_enable, delay_or_flag]`. `robot_manager.py`
  locates the pick-up step (`suck_enable == 1`) and also patches the approach/retract steps immediately
  before/after it by comparing Z heights.
- `FW_DOBOT/modularAssembly/order_data` — JSON written externally (Node-RED) describing the current part
  and color to assemble; read by `assembly_NR.py`.
- `YOLO/camera_robot_homography.npy` (+ a `.json` mirror) — the 3×3 perspective-transform matrix produced
  by calibration and consumed by `robot_manager.transform_pixel_to_robot_coords`.

**Component naming convention**: detections are named `"<color>-<partType>"` (e.g. `"red-trainCabin"`).
`component_detector.py` deliberately swaps `trainBase` ↔ `trainWheels` in detection output — the two class
labels were mixed up in the trained YOLO model, and this swap is a compensating fix, not a bug. Don't
"correct" it without checking whether the underlying model/label set has changed.

**Two independent Dobot control layers exist and are not interchangeable:**
- `FW_DOBOT/modularAssembly/lib/` (`interface.py`, `message.py`, `parsers.py`, `dobot.py`) — a low-level,
  hand-rolled implementation of the Dobot serial protocol (this repo's own code, not vendored). `Interface`
  exposes near-1:1 wrappers over protocol commands (homing, PTP moves, jog, end-effector, queue control);
  `Dobot` in `lib/dobot.py` is a thin convenience wrapper over `Interface`. Used by `robot_manager.py` and
  `calibrate_robot.py` for calibration, where fine-grained control and queue-index-based waiting is needed.
- `pydobotplus` (vendored in `FW_DOBOT/pydobotplus-master/`, installed as a normal pip package) — the
  higher-level driver actually used by the production assembly/conveyor scripts (`assembly_NR.py`,
  `conveyor_*.py`) for moves and conveyor-belt control. `pydobot-master/` is the older upstream library
  `pydobotplus` was forked from; it's kept for reference and isn't imported by any script in this repo.

**Calibration** (`YOLO/calibrate_robot.py`, `YOLO/checkerboard_find.py`, entry point
`YOLO/main_calibration.py`, driven from `main.py` when `calibration_mode: True`) finds checkerboard
corners in one camera frame, jogs the physical Dobot (with a pen attached) to a random subset of those
corners to record the matching robot coordinates, and fits the camera→robot homography saved to
`camera_robot_homography.npy`. `FW_DOBOT/modularAssembly/dobot_calibrate_5G.py` is a separate, simpler
firmware-homing-only script (`main.py` runs it as a first step before the camera calibration proper).
Tunable thresholds/positions live as module-level constants at the top of `calibrate_robot.py`
(`CHECKERBOARD_DIMENSIONS`, `SQUARE_SIZE_MM`, `SIMPLE_THRESH_VALUE`, `DOBOT_HOME_*`,
`DOBOT_CALIBRATION_Z`) — see `YOLO/README.txt` for how to tune them by hand.

**Camera capture**: `YOLO/camera_capture.py` is the current module used by `main.py`/`calibrate_robot.py`
(exposes `capture_and_save_single_image`); `YOLO/china_cam.py` is an earlier standalone/interactive
version of the same Hikvision-SDK capture logic kept for reference, not imported elsewhere. Both hardcode
`sys.path.append("/opt/MVS/Samples/aarch64/Python/MvImport")` to reach the vendored `MvCameraControl_class`
from the MVS SDK install — this only works once the MVS SDK is installed at that path.

## Notes for making changes

- `FW_DOBOT/modularAssembly/lib/` is duplicated verbatim inside `YOLO/lib/` (identical files) so that
  `YOLO/robot_manager.py` and `YOLO/calibrate_robot.py` can import it without `modularAssembly` being a
  proper installed package — both copies exist by design (see the `sys.path.insert` dance at the top of
  those files), so a fix to the Dobot protocol layer must be applied to **both** copies to stay in sync.
- Nearly every path in `YOLO/` and `FW_DOBOT/modularAssembly/` is a hardcoded absolute path under
  `/home/pi/Desktop/...`, assuming the repo is deployed at that exact location on the Pi. When moving or
  testing off-device, expect to patch these rather than finding a single config knob.
- `main.py`'s `DEFAULT_CONFIG` reads the Roboflow API key from the `ROBOFLOW_API_KEY` environment
  variable (never hardcode it back into `DEFAULT_CONFIG` — this repo is public). `model_id` is not
  secret and stays hardcoded.
- `ROBOFLOW_API_KEY` must be loadable from a **non-interactive** shell, since `run_save_img.sh` is
  invoked by Node-RED's `exec` node, not a login shell. `~/.bashrc` doesn't work for this on stock
  Raspberry Pi OS (its default `~/.bashrc` returns immediately for non-interactive shells, before ever
  reaching an `export` appended at the bottom of the file) — `run_save_img.sh` instead sources
  `~/.roboflow_env` explicitly, a per-Pi file outside this repo (`echo 'export ROBOFLOW_API_KEY="..."' >
  ~/.roboflow_env`). Don't "simplify" this back to relying on `~/.bashrc`.
- MVS SDK installs (every Pi set up so far) put `libMvCameraControl.so` under `/opt/MVS/lib/aarch64/`,
  but `MvCameraControl_class.py` hardcodes looking for it at `/opt/MVS/aarch64/libMvCameraControl.so` —
  needs `sudo ln -s /opt/MVS/lib/aarch64 /opt/MVS/aarch64` once per Pi after installing the `.deb`, or
  `camera_capture.py`'s import fails with `OSError: ... cannot open shared object file`. See
  `MVS/README.md`. Unlike the API key, this is a filesystem symlink so it isn't sensitive to
  interactive vs. non-interactive shells.
