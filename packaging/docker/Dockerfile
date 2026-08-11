# Headless Intel NPU Tools: the MCP server and the tools that need no desktop.
#
# Deliberately not the whole product. Screenshots, the clipboard, the control
# panel and the global shortcuts all work by talking to a desktop that a
# container has no access to, so this image carries semantic_search,
# context_filter, transcribe_audio, ocr_image and the MCP server, and nothing
# that would pretend to be a desktop application.
#
# The NPU is reached by passing the host's device through. The kernel driver
# (intel_vpu) and the firmware stay on the host; what has to be inside the
# image is the userspace half — Intel's user-mode driver and compiler, and the
# Level Zero loader OpenVINO calls into. Those are pinned by exact asset URL
# rather than tracked, because their compatibility is with the host's *kernel*
# driver and a silent upgrade is exactly what breaks that.
#
# The models are not baked in. They are ~800 MB, separately licensed, and
# belong to the user, so mount a directory at /models instead. See
# scripts/test-npu-container.sh, which builds and runs this correctly.
FROM ubuntu:24.04

# Intel publishes one tarball per release, containing the .deb files, and its
# name carries a build id that cannot be derived from the version. Bump both
# together, from https://github.com/intel/linux-npu-driver/releases
ARG NPU_DRIVER_TAG=v1.35.0
ARG NPU_DRIVER_ASSET=linux-npu-driver-v1.35.0.20260722-29947505341-ubuntu2404.tar.gz
# https://github.com/oneapi-src/level-zero/releases
ARG LEVEL_ZERO_TAG=v1.32.0
ARG LEVEL_ZERO_ASSET=libze1_1.32.0+u24.04_amd64.deb

ENV DEBIAN_FRONTEND=noninteractive
ENV INTEL_NPU_TOOLS_HOME=/models
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime dependencies, matching what the .deb declares. tesseract and ffmpeg
# are needed by the OCR and audio paths; pciutils is what intel-npu-info reads.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip \
      ffmpeg tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara \
      pciutils ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Intel's NPU userspace. There is no repository to add: these are release
# assets, which is why they are fetched by URL and why the versions above are
# the thing to change when this stops working.
#
# Not done in /tmp. apt drops privileges to the _apt user and needs a writable
# /tmp to do it; unpacking a tarball there can leave that directory with
# permissions apt cannot use, and the failure it then reports is about
# repository signatures, which sends you looking in entirely the wrong place.
RUN set -eux; \
    workdir=/opt/npu-driver; mkdir -p "$workdir"; cd "$workdir"; \
    curl -fsSLO "https://github.com/oneapi-src/level-zero/releases/download/${LEVEL_ZERO_TAG}/${LEVEL_ZERO_ASSET}"; \
    curl -fsSLO "https://github.com/intel/linux-npu-driver/releases/download/${NPU_DRIVER_TAG}/${NPU_DRIVER_ASSET}"; \
    tar xf "${NPU_DRIVER_ASSET}"; \
    chmod 1777 /tmp; \
    apt-get update; \
    apt-get install -y --no-install-recommends $(find "$workdir" -name '*.deb' | sort); \
    cd /; rm -rf "$workdir" /var/lib/apt/lists/*

# The toolkit itself, from the tree being built rather than from a release, so
# that this image tests the code in front of you.
COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
COPY scripts/download-models.py /src/scripts/download-models.py
RUN pip install --break-system-packages --no-cache-dir /src

# A place for the models to be mounted. Left empty on purpose: an image that
# carried them would be several times this size and would redistribute
# somebody else's weights.
RUN mkdir -p /models
VOLUME /models

# stdio, because that is how an agent speaks to an MCP server. Override the
# command to run any of the other entry points.
ENTRYPOINT []
CMD ["intel-npu-mcp"]
