FROM python:3.11-slim

ARG ARTIFACT_FEED=py-packages
ARG ARTIFACT_FEED_TOKEN

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1

RUN mkdir -p utilities/mongotools logs && \
    apt-get update && \
    apt-get install -y \
        build-essential \
        gcc \
        ffmpeg \
        wget && \
    wget -O /tmp/mongodb-database-tools.tgz https://fastdl.mongodb.org/tools/db/mongodb-database-tools-ubuntu1804-x86_64-100.6.0.tgz && \
    tar -xf /tmp/mongodb-database-tools.tgz -C /app/utilities/mongotools --strip-components 1 && \
    rm -f /tmp/mongodb-database-tools.tgz && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt


# CPU-only torch + torchaudio (no CUDA) for Silero VAD — saves ~6 GB
# vs default wheels.  Both must come from the CPU index; if torchaudio
# is pulled transitively by silero-vad it defaults to the CUDA build
# and imports fail at runtime with libcudart.so.* not found.
RUN python -m pip install \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.4.1 torchaudio==2.4.1
RUN python -m pip install silero-vad
RUN python -m pip install \
    -r requirements.txt \
    --extra-index-url=https://${ARTIFACT_FEED}:${ARTIFACT_FEED_TOKEN}@pkgs.dev.azure.com/dcl525/_packaging/${ARTIFACT_FEED}/pypi/simple/

RUN python -m pip install uvloop

COPY . .

# RUN apt-get update && apt-get dist-upgrade -y

# Run tests during build
# RUN pytest || (echo "Tests failed" && exit 1)

EXPOSE 80

CMD ["bash", "startup.sh"]