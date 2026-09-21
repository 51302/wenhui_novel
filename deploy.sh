#!/usr/bin/env bash

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
MAX_RETRIES=30
RETRY_DELAY=5

cd "$PROJECT_DIR"

print_header() {
    printf '\n============================================================\n'
    printf '  Wenhui Novel - Deploy Script\n'
    printf '============================================================\n\n'
}

usage() {
    printf 'Usage:\n'
    printf '  ./deploy.sh start    - Start all services\n'
    printf '  ./deploy.sh stop     - Stop all services\n'
    printf '  ./deploy.sh restart  - Restart all services\n'
}

check_environment() {
    if ! command -v docker >/dev/null 2>&1; then
        printf '  ERROR: Docker is not installed!\n'
        printf '  Please install Docker Desktop first.\n'
        return 1
    fi
    printf '  OK: Docker is installed\n'

    if ! docker compose version >/dev/null 2>&1; then
        printf '  ERROR: Docker Compose is not available!\n'
        return 1
    fi
    printf '  OK: Docker Compose is available\n'

    if [[ ! -f "$COMPOSE_FILE" ]]; then
        printf '  ERROR: docker-compose.yml not found!\n'
        return 1
    fi
    printf '  OK: docker-compose.yml found\n'
}

start_services() {
    printf '[ACTION] Starting Services...\n\n'

    printf '[STEP 1/6] Checking Environment...\n'
    check_environment || return 1

    printf '\n[STEP 2/6] Cleaning Old Containers...\n'
    for container in wenhui-frontend wenhui-backend wenhui-natapp wenhui-es wenhui-seaweedfs-master wenhui-seaweedfs-volume wenhui-seaweedfs-filer; do
        docker stop "$container" >/dev/null 2>&1 || true
        docker rm -f "$container" >/dev/null 2>&1 || true
    done
    printf '  OK: Old containers cleaned\n'

    printf '\n[STEP 3/6] Building Docker Images...\n'
    if ! docker compose build --pull frontend backend; then
        printf '  ERROR: Image build failed!\n'
        return 1
    fi
    printf '  OK: Images built successfully\n'

    printf '\n[STEP 4/6] Starting Services...\n'
    if ! docker compose up -d; then
        printf '  ERROR: Failed to start services!\n'
        return 1
    fi
    printf '  OK: Services started\n'

    printf '\n[STEP 5/6] Waiting for Services...\n'
    printf '  Waiting for backend to be ready...\n'
    local retry_count=0
    while ! curl -fsS -o /dev/null http://localhost:8000/api/health; do
        retry_count=$((retry_count + 1))
        printf '  Attempt %d/%d...\n' "$retry_count" "$MAX_RETRIES"
        if (( retry_count >= MAX_RETRIES )); then
            printf '  ERROR: Backend timeout!\n'
            return 1
        fi
        sleep "$RETRY_DELAY"
    done
    printf '  OK: Backend is ready\n'

    printf '  Waiting for frontend...\n'
    sleep 3
    if curl -fsS -o /dev/null http://localhost/; then
        printf '  OK: Frontend is ready\n'
    else
        printf '  WARN: Frontend may still be starting...\n'
    fi

    printf '\n[STEP 6/6] Service Status...\n'
    docker compose ps

    printf '\n============================================================\n'
    printf '  START COMPLETE!\n'
    printf '============================================================\n\n'
    printf '  Local:           http://localhost\n'
    printf '  Local API:       http://localhost:8000\n'
    printf '  Public:          https://wenhui.nat100.top\n\n'
}

stop_services() {
    printf '[ACTION] Stopping Services...\n\n'

    if ! docker compose down; then
        printf '  ERROR: Failed to stop services!\n'
        return 1
    fi
    printf '  OK: All services stopped\n'

    printf '\n============================================================\n'
    printf '  STOP COMPLETE!\n'
    printf '============================================================\n\n'
    printf '  All containers have been stopped and removed.\n\n'
}

restart_services() {
    printf '[ACTION] Restarting Services...\n\n'

    docker compose down
    printf '  OK: Services stopped\n\n'

    if ! docker compose up -d; then
        printf '  ERROR: Failed to restart services!\n'
        return 1
    fi
    printf '  OK: Services restarted\n'

    printf '\n============================================================\n'
    printf '  RESTART COMPLETE!\n'
    printf '============================================================\n\n'
}

print_header

case "${1:-}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    *)
        usage
        [[ -n "${1:-}" ]] && exit 1
        exit 0
        ;;
esac
