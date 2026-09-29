# googly-vr — dev tasks (Poetry project; touchy-pad is a path dep on ../../app).

# List available recipes.
default:
    @just --list

# Create/update the venv and install deps (incl. the touchy-pad path dep).
install:
    poetry install --no-interaction

# Run the pytest suite.
test: install
    poetry run pytest -q

# Format + lint.
lint:
    poetry run ruff format src tests
    poetry run ruff check --fix src tests

# Broadcast fake EyeTrackVR tracking on UDP localhost:9000.
sim-eyes *args: install
    poetry run sim-eyes {{args}}

# Run the eye renderer (connects to USB, or the sim via TOUCHY_SIM_URL).
run *args: install
    poetry run googly-vr {{args}}
