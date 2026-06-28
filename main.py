import os
from pathlib import Path

import yaml
from dotenv import dotenv_values
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
ENV_NAME = os.environ.get("APP_ENV", "development")

# Layer 1: hardcoded defaults
DEFAULTS = {
    "port": 8000,
    "workers": 1,
    "debug": False,
    "log_level": "info",
    "api_key": "default-secret-000",
}


def load_yaml_layer():
    """Layer 2: config.<env>.yaml"""
    path = BASE_DIR / f"config.{ENV_NAME}.yaml"
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data or {}


def _strip_app_prefix(raw_key):
    """Map APP_FOO -> foo, and the special NUM_WORKERS -> workers alias."""
    if raw_key == "NUM_WORKERS":
        return "workers"
    if raw_key.startswith("APP_"):
        return raw_key[len("APP_"):].lower()
    return None


def load_dotenv_layer():
    """Layer 3: .env file on disk (parsed directly, NOT merged into os.environ
    so it stays distinct from the real OS-level layer)."""
    path = BASE_DIR / ".env"
    result = {}
    if not path.exists():
        return result
    for raw_key, raw_val in dotenv_values(path).items():
        if raw_val is None:
            continue
        key = _strip_app_prefix(raw_key)
        if key:
            result[key] = raw_val
    return result


def load_os_env_layer():
    """Layer 4: real OS-level environment variables (APP_ prefix / NUM_WORKERS)."""
    result = {}
    for raw_key, raw_val in os.environ.items():
        key = _strip_app_prefix(raw_key)
        if key:
            result[key] = raw_val
    return result


def coerce(key, value):
    if key in ("port", "workers"):
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    return str(value)


@app.get("/effective-config")
def effective_config(request: Request):
    merged = {}
    merged.update(DEFAULTS)
    merged.update(load_yaml_layer())
    merged.update(load_dotenv_layer())
    merged.update(load_os_env_layer())

    # Layer 5: CLI overrides via repeated ?set=key=value (highest precedence)
    for raw in request.query_params.getlist("set"):
        if "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        k = k.strip()
        if k == "NUM_WORKERS":
            k = "workers"
        merged[k] = v.strip()

    out = {}
    for k in ("port", "workers", "debug", "log_level", "api_key"):
        out[k] = coerce(k, merged.get(k))

    out["api_key"] = "****"
    return out


@app.get("/")
def health():
    return {"status": "ok"}
