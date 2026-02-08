"""Embedding service with OpenAI/Ollama support"""

from typing import Protocol, Callable, TypeVar
import random
import time
import httpx

from ..config import get_settings

T = TypeVar("T")


def _retry_with_backoff(
    operation: Callable[[], T],
    *,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> T:
    """带指数退避的重试执行器，用于缓解 RPM/网络抖动导致的失败。
    
    参数:
        operation: 无参可调用对象，执行一次请求并返回结果。
        max_retries: 最大重试次数，包含首次尝试。
        base_delay: 退避基础秒数，用于指数退避计算。
        max_delay: 单次等待的上限秒数。
    
    返回:
        operation 的返回值。
    
    规则:
        仅对可判定为限流/网络异常的错误进行重试，其他错误直接抛出。
    """
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as exc:
            message = str(exc).lower()
            exc_name = exc.__class__.__name__
            retryable_names = {
                "ratelimiterror",
                "apitimeouterror",
                "apiconnectionerror",
                "internalservererror",
                "serviceunavailableerror",
            }
            retryable_messages = (
                "rate limit",
                "rpm limit",
                "too many requests",
                "429",
                "502",
                "503",
                "504",
                "timeout",
                "timed out",
                "connection",
                "temporarily",
            )
            should_retry = (
                isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
                or exc_name in retryable_names
                or any(token in message for token in retryable_messages)
            )
            if not should_retry or attempt >= max_retries - 1:
                raise
            # 指数退避 + 抖动，避免同一时间齐刷刷重试
            delay = min(max_delay, base_delay * (2 ** attempt))
            delay += random.uniform(0, base_delay)
            time.sleep(delay)


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers"""
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts"""
        ...


class OpenAIEmbedding:
    """OpenAI embedding provider"""
    
    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.embedding_model
        
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API"""
        import openai
        
        client = openai.OpenAI(api_key=self.api_key)
        
        # OpenAI has a limit on batch size
        batch_size = 100
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = _retry_with_backoff(
                lambda: client.embeddings.create(
                    input=batch,
                    model=self.model,
                )
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)
        
        return all_embeddings


class OllamaEmbedding:
    """Ollama embedding provider"""
    
    def __init__(self, base_url: str | None = None, model: str | None = None):
        settings = get_settings()
        self.base_url = base_url or settings.ollama_base_url
        self.model = model or "nomic-embed-text"
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using Ollama"""
        embeddings = []
        
        for text in texts:
            def _request():
                """请求单条嵌入并返回响应 JSON。"""
                response = httpx.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                    timeout=60.0,
                )
                response.raise_for_status()
                return response.json()

            data = _retry_with_backoff(_request)
            embeddings.append(data["embedding"])
        
        return embeddings


class SiliconFlowEmbedding:
    """SiliconFlow embedding provider (OpenAI-compatible API)"""
    
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.siliconflow_api_key
        self.base_url = base_url or settings.siliconflow_base_url
        self.model = model or settings.embedding_model or "BAAI/bge-large-zh-v1.5"
        
        if not self.api_key:
            raise ValueError("SiliconFlow API key is required")
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using SiliconFlow API"""
        import openai
        
        client = openai.OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        
        batch_size = 24  # SiliconFlow API limit
        all_embeddings = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = _retry_with_backoff(
                lambda: client.embeddings.create(
                    input=batch,
                    model=self.model,
                )
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)
        
        return all_embeddings


def get_embedding_provider() -> EmbeddingProvider:
    """Get embedding provider based on settings"""
    settings = get_settings()
    
    if settings.embedding_provider == "openai":
        return OpenAIEmbedding()
    elif settings.embedding_provider == "ollama":
        return OllamaEmbedding()
    elif settings.embedding_provider == "siliconflow":
        return SiliconFlowEmbedding()
    else:
        raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
