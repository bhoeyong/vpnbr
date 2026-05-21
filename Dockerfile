# Dockerfile (可选，用于Render部署)
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖：ffmpeg 是 yt-dlp 合并视频/音频必需的
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 创建非root用户运行
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--timeout", "300"]