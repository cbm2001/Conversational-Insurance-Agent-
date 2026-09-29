from __future__ import annotations

import os
import ssl
from typing import Union

import certifi
import httpx
from openai import OpenAI

VerifySetting = Union[bool, str, ssl.SSLContext]
_ssl_configured = False


def configure_ssl() -> None:
    """Prepare TLS verification for OpenAI HTTP calls (Windows/Anaconda-safe)."""
    global _ssl_configured
    if _ssl_configured:
        return
    _ssl_configured = True

    ca_path = certifi.where()
    os.environ.setdefault("SSL_CERT_FILE", ca_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)

    try:
        import truststore  # noqa: WPS433

        truststore.inject_into_ssl()
    except ImportError:
        pass


def _ssl_verify_setting() -> VerifySetting:
    """
    OPENAI_SSL_VERIFY:
      - auto (default): OS trust store if truststore is installed, else certifi bundle
      - system: OS trust store (requires truststore on Windows)
      - certifi: Mozilla CA bundle only
      - false: disable verification (local debugging only)
    """
    mode = (os.getenv("OPENAI_SSL_VERIFY") or "auto").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return False
    if mode == "certifi":
        return certifi.where()
    if mode == "system":
        try:
            import truststore  # noqa: WPS433

            ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(cafile=certifi.where())
            return ctx
        except ImportError as exc:
            raise RuntimeError(
                "OPENAI_SSL_VERIFY=system requires: pip install truststore"
            ) from exc
    # auto
    try:
        import truststore  # noqa: WPS433

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cafile=certifi.where())
        return ctx
    except ImportError:
        return certifi.where()


def llm_provider() -> str:
    return (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()


def llm_model() -> str:
    default_model = "llama3.2:latest" if llm_provider() == "ollama" else "gpt-4o-mini"
    return (os.getenv("LLM_MODEL") or default_model).strip()


def create_llm_client() -> OpenAI:
    provider = llm_provider()
    if provider == "ollama":
        api_key = (os.getenv("OLLAMA_API_KEY") or "ollama").strip()
        base_url = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1").strip()
    elif provider == "openai":
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Set LLM_PROVIDER=ollama for local testing "
                "or add an OpenAI key to apps/insurance_claims/.env."
            )
        base_url = None
    else:
        raise RuntimeError("LLM_PROVIDER must be either 'ollama' or 'openai'.")

    configure_ssl()
    verify = _ssl_verify_setting()
    http_client = httpx.Client(verify=verify, timeout=60.0)
    client_args: dict[str, object] = {"api_key": api_key, "http_client": http_client}
    if base_url:
        client_args["base_url"] = base_url
    return OpenAI(**client_args)
