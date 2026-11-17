"""Install the pinned local face models without accepting mutable downloads."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen


MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def install() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (url, expected) in MODELS.items():
        destination = MODEL_DIR / filename
        if destination.is_file() and digest(destination) == expected:
            continue
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(dir=MODEL_DIR, delete=False) as temporary:
                temporary_name = temporary.name
                with urlopen(url, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        temporary.write(chunk)
            temporary_path = Path(temporary_name)
            if digest(temporary_path) != expected:
                raise RuntimeError(f"Checksum inválido para {filename}.")
            os.replace(temporary_path, destination)
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)


if __name__ == "__main__":
    install()
    print("Modelos faciais locais instalados e verificados.")
