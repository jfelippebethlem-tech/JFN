FROM python:3.9-slim-buster

WORKDIR /app

RUN pip install torch torchvision --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install transformers diffusers accelerate scipy

COPY generate_image.py .

CMD ["python", "generate_image.py"]
