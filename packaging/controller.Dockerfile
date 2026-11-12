FROM antigravity-obs-controller:1
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["python3", "tools/obs_controller.py", "cycle"]
