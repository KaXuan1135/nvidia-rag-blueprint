import base64
import binascii
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from nemotron_ocr.inference.pipeline import NemotronOCR
from pydantic import BaseModel


MODEL_DIR = os.getenv("NEMOTRON_OCR_MODEL_DIR", "/opt/models/nemotron-ocr-v1")
_model: NemotronOCR | None = None
_model_lock = threading.Lock()


class ImageInput(BaseModel):
    type: str
    url: str


class OCRRequest(BaseModel):
    input: list[ImageInput]
    merge_levels: list[str] | None = None


def decode_data_url(value: str) -> bytes:
    try:
        header, encoded = value.split(",", 1)
        if not header.startswith("data:image/") or ";base64" not in header:
            raise ValueError
        base64.b64decode(encoded, validate=True)
        return encoded.encode("ascii")
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Invalid base64 image data URL") from exc


def prediction_to_detection(prediction: dict[str, Any]) -> dict[str, Any]:
    left = max(0.0, min(1.0, float(prediction["left"])))
    right = max(0.0, min(1.0, float(prediction["right"])))
    top = max(0.0, min(1.0, float(prediction["lower"])))
    bottom = max(0.0, min(1.0, float(prediction["upper"])))

    return {
        "text_prediction": {
            "text": str(prediction["text"]),
            "confidence": max(0.0, min(1.0, float(prediction["confidence"]))),
        },
        "bounding_box": {
            "points": [
                {"x": left, "y": top},
                {"x": right, "y": top},
                {"x": right, "y": bottom},
                {"x": left, "y": bottom},
            ]
        },
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _model
    _model = NemotronOCR(model_dir=MODEL_DIR)
    yield
    _model = None


app = FastAPI(title="Nemotron OCR v1 for DGX Spark", lifespan=lifespan)


@app.get("/v1/health/live")
@app.get("/v1/health/ready")
def health() -> dict[str, str]:
    if _model is None:
        raise HTTPException(status_code=503, detail="OCR model is not loaded")
    return {"status": "ready", "model": "nvidia/nemotron-ocr-v1"}


@app.post("/v1/infer")
def infer(request: OCRRequest) -> dict[str, list[dict[str, Any]]]:
    if _model is None:
        raise HTTPException(status_code=503, detail="OCR model is not loaded")
    if not request.input:
        raise HTTPException(status_code=422, detail="At least one image is required")

    merge_levels = request.merge_levels or ["paragraph"] * len(request.input)
    if len(merge_levels) != len(request.input):
        raise HTTPException(status_code=422, detail="merge_levels must match the input batch size")

    results = []
    with _model_lock:
        for item, merge_level in zip(request.input, merge_levels):
            if item.type != "image_url":
                raise HTTPException(status_code=422, detail="Only image_url input is supported")
            try:
                predictions = _model(decode_data_url(item.url), merge_level=merge_level)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            results.append(
                {
                    "text_detections": [
                        prediction_to_detection(prediction) for prediction in predictions
                    ]
                }
            )

    return {"data": results}
