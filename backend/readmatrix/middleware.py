"""API 观测性中间件"""

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# 配置结构化日志
logger = logging.getLogger("readmatrix.api")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    请求观测中间件，记录每个请求的关键信息：
    - request_id: 唯一请求标识
    - method: HTTP 方法
    - path: 请求路径
    - status_code: 响应状态码
    - latency_ms: 请求耗时（毫秒）
    - client_ip: 客户端 IP
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        # 将 request_id 注入到 request.state，方便后续使用
        request.state.request_id = request_id

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"

        try:
            response = await call_next(request)
            status_code = response.status_code
            error = None
        except Exception as e:
            status_code = 500
            error = str(e)
            raise
        finally:
            latency_ms = (time.perf_counter() - start_time) * 1000

            # 结构化日志输出
            log_data = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "latency_ms": round(latency_ms, 2),
                "client_ip": client_ip,
            }

            if error:
                log_data["error"] = error
                logger.error(
                    f"[{request_id}] {request.method} {request.url.path} "
                    f"-> {status_code} ({latency_ms:.2f}ms) ERROR: {error}"
                )
            else:
                # 根据状态码选择日志级别
                if status_code >= 500:
                    logger.error(
                        f"[{request_id}] {request.method} {request.url.path} "
                        f"-> {status_code} ({latency_ms:.2f}ms)"
                    )
                elif status_code >= 400:
                    logger.warning(
                        f"[{request_id}] {request.method} {request.url.path} "
                        f"-> {status_code} ({latency_ms:.2f}ms)"
                    )
                else:
                    logger.info(
                        f"[{request_id}] {request.method} {request.url.path} "
                        f"-> {status_code} ({latency_ms:.2f}ms)"
                    )

        # 将 request_id 添加到响应头，方便客户端追踪
        response.headers["X-Request-ID"] = request_id
        return response


def setup_logging(log_level: str = "INFO") -> None:
    """配置日志格式"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
