# syntax=docker/dockerfile:1.7
FROM nvcr.io/nvidia/pytorch:25.09-py3

ARG TARGETARCH
ARG CUDA_ARCH_LIST=12.1+PTX

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_CUDA_ARCH_LIST=${CUDA_ARCH_LIST} \
    NEMOTRON_OCR_MODEL_DIR=/opt/models/nemotron-ocr-v1

COPY --from=nemotron_ocr_package / /opt/src/nemotron-ocr
COPY --from=nemotron_ocr_checkpoints / /opt/models/nemotron-ocr-v1

WORKDIR /opt/src/nemotron-ocr

RUN rm -f src/nemotron_ocr_cpp/*.so \
    && rm -rf build dist \
    && python -m pip install --no-cache-dir -U hatchling "setuptools>=68" \
    && BUILD_CPP_EXTENSION=1 BUILD_CPP_FORCE=1 ARCH=${TARGETARCH} \
       python -m pip install --no-cache-dir -v . --no-build-isolation \
    && python -c "import nemotron_ocr_cpp._nemotron_ocr_cpp"

RUN python -m pip install --no-cache-dir \
    fastapi==0.116.1 \
    uvicorn==0.35.0

WORKDIR /app
COPY services/nemotron-ocr-arm64/app.py .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
