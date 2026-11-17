"""Local face detection and embedding with pinned OpenCV models."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


MODEL_DIR = Path(__file__).resolve().parent / "models"
DETECTOR_PATH = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
MODEL_HASHES = {
    DETECTOR_PATH: "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    RECOGNIZER_PATH: "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
MODEL_VERSION = "opencv-sface-2021dec"
EMBEDDING_FLOATS = 128


class FaceError(ValueError):
    pass


def _verified(path: Path) -> str:
    if not path.is_file():
        raise FaceError("modelo_facial_nao_instalado")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    if checksum != MODEL_HASHES[path]:
        raise FaceError("modelo_facial_invalido")
    return str(path)


@lru_cache(maxsize=1)
def _models():
    try:
        import cv2
    except ImportError as error:
        raise FaceError("motor_facial_nao_instalado") from error
    detector = cv2.FaceDetectorYN.create(
        _verified(DETECTOR_PATH), "", (320, 320), 0.9, 0.3, 5000
    )
    recognizer = cv2.FaceRecognizerSF.create(_verified(RECOGNIZER_PATH), "")
    return cv2, detector, recognizer


def embedding(image_bytes: bytes):
    cv2, detector, recognizer = _models()
    import numpy as np

    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3:
        raise FaceError("foto_invalida")
    height, width = image.shape[:2]
    if width < 240 or height < 240:
        raise FaceError("rosto_imagem_pequena")
    detector.setInputSize((width, height))
    _status, faces = detector.detect(image)
    if faces is None or len(faces) == 0:
        raise FaceError("rosto_nao_detectado")
    if len(faces) != 1:
        raise FaceError("rosto_multiplos_detectados")

    face = faces[0]
    x, y, face_width, face_height = face[:4]
    if face_width < 100 or face_height < 100 or face_width * face_height < width * height * 0.08:
        raise FaceError("rosto_muito_distante")
    margin_x, margin_y = width * 0.02, height * 0.02
    if x < margin_x or y < margin_y or x + face_width > width - margin_x or y + face_height > height - margin_y:
        raise FaceError("rosto_fora_do_quadro")

    crop = image[max(0, int(y)):min(height, int(y + face_height)),
                 max(0, int(x)):min(width, int(x + face_width))]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if float(gray.mean()) < 40 or float(gray.mean()) > 220:
        raise FaceError("rosto_iluminacao_inadequada")
    if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < 35:
        raise FaceError("rosto_imagem_desfocada")

    aligned = recognizer.alignCrop(image, face)
    feature = recognizer.feature(aligned).reshape(-1).astype(np.float32)
    norm = float(np.linalg.norm(feature))
    if feature.size != EMBEDDING_FLOATS or not np.isfinite(feature).all() or norm <= 0:
        raise FaceError("rosto_perfil_invalido")
    return feature / norm


def enrollment_template(images: list[bytes]) -> bytes:
    import numpy as np

    if not 3 <= len(images) <= 5:
        raise FaceError("rosto_amostras_insuficientes")
    features = [embedding(image) for image in images]
    for index, first in enumerate(features):
        for second in features[index + 1:]:
            if float(np.dot(first, second)) < 0.38:
                raise FaceError("rosto_amostras_incompativeis")
    merged = np.mean(features, axis=0)
    norm = float(np.linalg.norm(merged))
    if norm <= 0:
        raise FaceError("rosto_perfil_invalido")
    return (merged / norm).astype("<f4").tobytes()


def similarity(template: bytes, probe) -> float:
    import numpy as np

    stored = np.frombuffer(template, dtype="<f4")
    if stored.size != EMBEDDING_FLOATS or not np.isfinite(stored).all():
        raise FaceError("rosto_perfil_invalido")
    return float(np.dot(stored, probe))
