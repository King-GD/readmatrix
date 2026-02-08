"""FastAPI application entry point"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .api import router
from .middleware import ObservabilityMiddleware, setup_logging


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    settings = get_settings()

    # 初始化日志
    setup_logging(log_level=getattr(settings, "log_level", "INFO"))

    app = FastAPI(
        title="ReadMatrix",
        description="Local-first personal knowledge platform with grounded Q&A",
        version="0.1.0",
    )

    # 观测性中间件（放在最外层，记录所有请求）
    app.add_middleware(ObservabilityMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(router)

    return app


# Create app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "readmatrix.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
