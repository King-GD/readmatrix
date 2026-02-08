"""Configuration management using Pydantic Settings"""

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # === User Configuration (required or with sensible defaults) ===
    vault_path: Path = Field(
        default=Path("./vault"),
        description="Path to Obsidian vault"
    )
    weread_folder: str = Field(
        default="微信读书",
        description="WeRead sync folder name within vault"
    )
    
    # === LLM Configuration ===
    llm_provider: str = Field(
        default="openai",
        description="LLM provider: openai | ollama | siliconflow"
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="LLM model name"
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key"
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL"
    )
    
    # === SiliconFlow Configuration ===
    siliconflow_api_key: str = Field(
        default="",
        description="SiliconFlow API key"
    )
    siliconflow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1",
        description="SiliconFlow API base URL"
    )
    
    # === Embedding Configuration ===
    embedding_provider: str = Field(
        default="openai",
        description="Embedding provider: openai | ollama | siliconflow"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name"
    )
    
    # === Index Configuration ===
    chunk_size: int = Field(
        default=500,
        description="Maximum chunk size in characters"
    )
    chunk_overlap: int = Field(
        default=50,
        description="Chunk overlap in characters"
    )
    
    # === Storage Configuration ===
    data_dir: Path = Field(
        default=Path("./data"),
        description="Data directory for SQLite and ChromaDB"
    )
    
    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "readmatrix.db"
    
    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"
    
    @property
    def weread_path(self) -> Path:
        return self.vault_path / self.weread_folder
    
    # === Server Configuration ===
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    cors_origins: list[str] = Field(default=["http://localhost:3000"])
    
    # === RAG Configuration ===
    retrieval_top_k: int = Field(default=5, description="Number of chunks to retrieve")
    retrieval_max_distance: float | None = Field(
        default=0.4,
        description="向量检索最大距离阈值，越小越严格；为 None 时不做过滤",
    )
    qa_note_ratio: int = Field(
        default=80,
        description="回答中笔记内容占比(0-100)，0 为完全模型回答，100 为完全基于笔记",
    )
    temperature: float = Field(default=0.5, description="LLM temperature")

    # === Reranker Configuration ===
    enable_reranker: bool = Field(
        default=True,
        description="是否启用 Reranker 重排序"
    )
    reranker_model: str = Field(
        default="BAAI/bge-reranker-v2-m3",
        description="Reranker 模型名称"
    )

    # === Context Window Configuration ===
    context_window: int = Field(
        default=1,
        description="检索时获取前后各 N 个相邻 chunk，0 表示禁用"
    )


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create settings singleton"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings"""
    global _settings
    _settings = Settings()
    return _settings
