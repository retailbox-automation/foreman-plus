FROM python:3.12-slim
# Static ffmpeg 7.x (~80MB): Debian bookworm's apt ffmpeg is 5.1 and lacks the
# newer live-HLS reconnect behavior.
COPY --from=mwader/static-ffmpeg:7.1 /ffmpeg /usr/local/bin/ffmpeg
WORKDIR /app
COPY live_brain/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY live_brain /app/live_brain
ENV PYTHONUNBUFFERED=1 FRAME_DIR=/tmp/frames
CMD ["python", "-m", "live_brain.server"]
