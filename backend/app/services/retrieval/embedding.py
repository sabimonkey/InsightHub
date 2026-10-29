import hashlib
import os

import httpx

from app.core.config import Settings
from app.services.llm.provider import is_local_base_url
from app.services.retrieval.constants import EMBEDDING_DIMENSIONS


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EmbeddingProvider:
    provider_type = "GENERIC"
    is_local = False
    model = ""

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], int | None]:
        raise NotImplementedError


class FakeEmbeddingProvider(EmbeddingProvider):
    provider_type = "FAKE"
    is_local = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.model = "fake-embedding"
        self.base_url = "http://127.0.0.1/fake-embedding"

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], int | None]:
        return [_vector(text, self.dimensions) for text in texts], None


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(self, *, provider_type: str, base_url: str, model: str, api_key: str, is_local: bool, timeout: float, dimensions: int) -> None:
        self.provider_type = provider_type
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.is_local = is_local and is_local_base_url(base_url)
        self.timeout = timeout
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> tuple[list[list[float]], int | None]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError("PROVIDER_UNAVAILABLE", type(exc).__name__) from exc
        if response.status_code >= 400:
            raise EmbeddingError("PROVIDER_UNAVAILABLE", f"embedding HTTP {response.status_code}")
        body = response.json()
        rows = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [list(item.get("embedding") or []) for item in rows]
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        tokens = usage.get("prompt_tokens") or usage.get("total_tokens")
        return vectors, tokens


def _vector(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    lowered = text.casefold()
    if "sandbox" in lowered or "沙箱" in text:
        vector[0] = 1.0
    elif "robot" in lowered or "机器人" in text:
        vector[1] = 1.0
    else:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vector[digest[0] % dimensions] = 1.0
    return vector


def provider_from_settings(settings: Settings) -> EmbeddingProvider | None:
    if settings.embedding_enable_fake:
        return FakeEmbeddingProvider(settings.embedding_dimensions)
    if settings.local_embedding_base_url and settings.local_embedding_model and is_local_base_url(settings.local_embedding_base_url):
        return OpenAICompatibleEmbeddingProvider(
            provider_type="LOCAL_OPENAI_COMPATIBLE",
            base_url=settings.local_embedding_base_url,
            model=settings.local_embedding_model,
            api_key="",
            is_local=True,
            timeout=settings.llm_timeout_seconds,
            dimensions=settings.embedding_dimensions,
        )
    if settings.generic_embedding_base_url and settings.generic_embedding_model and (os.environ.get("GENERIC_EMBEDDING_API_KEY") or settings.generic_embedding_api_key):
        return OpenAICompatibleEmbeddingProvider(
            provider_type="GENERIC_OPENAI_COMPATIBLE",
            base_url=settings.generic_embedding_base_url,
            model=settings.generic_embedding_model,
            api_key=os.environ.get("GENERIC_EMBEDDING_API_KEY") or settings.generic_embedding_api_key,
            is_local=False,
            timeout=settings.llm_timeout_seconds,
            dimensions=settings.embedding_dimensions,
        )
    if settings.siliconflow_embedding_base_url and settings.siliconflow_embedding_model and (os.environ.get("SILICONFLOW_EMBEDDING_API_KEY") or settings.siliconflow_embedding_api_key):
        return OpenAICompatibleEmbeddingProvider(
            provider_type="SILICONFLOW",
            base_url=settings.siliconflow_embedding_base_url,
            model=settings.siliconflow_embedding_model,
            api_key=os.environ.get("SILICONFLOW_EMBEDDING_API_KEY") or settings.siliconflow_embedding_api_key,
            is_local=False,
            timeout=settings.llm_timeout_seconds,
            dimensions=settings.embedding_dimensions,
        )
    return None
