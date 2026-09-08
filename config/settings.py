import os

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
DEBUG = os.getenv("FLASK_DEBUG", "1") == "1"

# Required by recent Earth Engine authentication/initialization workflows.
# Set it before starting Flask, for example:
# Windows CMD: set EARTH_ENGINE_PROJECT=my-project-id
# PowerShell:   $env:EARTH_ENGINE_PROJECT="my-project-id"
# Linux/macOS:  export EARTH_ENGINE_PROJECT=my-project-id
EARTH_ENGINE_PROJECT = os.getenv("EARTH_ENGINE_PROJECT", "")
