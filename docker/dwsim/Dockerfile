# DWSIM for `cheme process simulate`: the official Linux package (.NET 8) and the worker.
#
#   docker build --platform linux/amd64 -t cheme-dwsim:9.0.5 -f docker/dwsim/Dockerfile .
#
# The package is amd64 only; on Apple silicon the image runs emulated (slower, same results).
FROM --platform=linux/amd64 ubuntu:24.04

ARG DWSIM_VERSION=9.0.5
ARG DWSIM_SHA256=52c041b1d659ea26e22750e8b7045c7bc68d3d95f6384abe28d07d967eafa20c

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 python3-venv dotnet-runtime-8.0 coinor-libipopt1v5 \
        libgdiplus libfontconfig1 \
    && curl -fsSL -o /tmp/dwsim.deb \
        "https://github.com/DanWBR/dwsim/releases/download/v${DWSIM_VERSION}/dwsim_${DWSIM_VERSION}-amd64.deb" \
    && echo "${DWSIM_SHA256}  /tmp/dwsim.deb" | sha256sum -c - \
    && apt-get install -y --no-install-recommends /tmp/dwsim.deb \
    && rm -rf /tmp/dwsim.deb /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir pythonnet==3.0.5

ENV CHEME_DWSIM_PATH=/usr/local/lib/dwsim \
    LD_LIBRARY_PATH=/usr/local/lib/dwsim:/usr/local/lib/dwsim/ThermoCS \
    DOTNET_ROOT=/usr/lib/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1
# cheme-as-code mounts its own worker over this copy at run time (integrations/dwsim.py)
COPY src/chemeascode/integrations/dwsim_worker.py /opt/cheme/dwsim_worker.py
ENTRYPOINT ["/opt/venv/bin/python", "-I", "/opt/cheme/dwsim_worker.py"]
