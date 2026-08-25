FROM python:3.12-slim
WORKDIR /app
COPY live_brain/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY live_brain /app/live_brain
ENV PYTHONUNBUFFERED=1 FRAME_DIR=/tmp/frames
CMD ["python", "-m", "live_brain.server"]
