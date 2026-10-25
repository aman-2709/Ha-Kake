# Ha-Kake dashboard + simulator as an OCI image (docs/CONTAINER.md).
#
#   podman build --platform linux/arm64 -t ha-kake .      # for a TDA4 / Jacinto 7 board
#
# The app binds 127.0.0.1 only, on purpose (SECURITY.md). Run it with host
# networking, not -p: a published port cannot reach a container's own loopback.
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312-minimal
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_NO_CACHE_DIR=1 \
    HAKAKE_DATA_DIR=/data

USER 0
WORKDIR /app

# Dependencies first, so a code change does not reinstall them. pytest is for
# the test suite, not the image.
COPY requirements.txt /tmp/requirements.txt
RUN sed -i '/^pytest/d' /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Explicit paths, not `COPY . .`: a build that ignores both ignore files still
# cannot pick up config.local.json, a database or research/.
COPY *.py LICENSE NOTICE ./
COPY vehicles/ vehicles/
COPY simulator/ simulator/
COPY web/*.py web/
COPY web/templates/ web/templates/
COPY web/static/ web/static/
COPY web/layouts/ web/layouts/

# The data folder is the only place the app writes. A named volume mounted
# here takes this owner.
RUN mkdir /data && chown 1001:0 /data && chmod 0770 /data
USER 1001

LABEL org.opencontainers.image.title="Ha-Kake" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

CMD ["python", "web/app.py", "--adapter", "sim"]
