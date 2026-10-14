FROM python:3.11-slim

WORKDIR /app

# 依赖层（先装依赖，利用构建缓存）
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# 前端 + 入口脚本
COPY app/ ./app/
COPY scripts/ ./scripts/

EXPOSE 8000
CMD ["python", "scripts/run_api.py"]
