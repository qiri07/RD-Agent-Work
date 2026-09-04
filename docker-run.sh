#!/bin/bash
# Start dockerd as user if not running
if ! socat UNIX-CONNECT:/tmp/docker-user.sock 2>/dev/null; then
    # Try to start user docker
    mkdir -p ~/.docker/run
    dockerd --host=unix:///tmp/docker-user.sock --rootless &
fi
DOCKER_HOST=unix:///tmp/docker-user.sock /usr/bin/docker "$@"
