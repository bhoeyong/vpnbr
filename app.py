# app.py
import os
import re
import uuid
import shutil
import tempfile
from pathlib import Path

import yt_dlp
from flask import Flask, render_template, request, send_file, jsonify, after_this_request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 限制上传大小为1GB，实际上传的是URL

# 支持的域名模式
YOUTUBE_PATTERNS = [
    r'(?:www\.)?youtube\.com/watch\?v=',
    r'(?:www\.)?youtu\.be/',
    r'(?:www\.)?youtube\.com/shorts/',
    r'(?:www\.)?youtube\.com/playlist\?list='
]

def is_youtube_url(url):
    """简单检查是否为YouTube链接"""
    if not url:
        return False
    for pattern in YOUTUBE_PATTERNS:
        if re.search(pattern, url):
            return True
    return False

def get_video_info(url):
    """获取视频标题和可用格式（用于前端展示）"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            # 收集视频格式（带分辨率的）
            for f in info.get('formats', []):
                if f.get('vcodec') != 'none' and f.get('height'):
                    formats.append({
                        'format_id': f['format_id'],
                        'ext': f['ext'],
                        'height': f['height'],
                        'note': f.get('format_note', ''),
                        'filesize': f.get('filesize'),
                    })
            # 去重（按高度）
            unique_formats = {}
            for f in formats:
                height = f['height']
                if height not in unique_formats or f['ext'] == 'mp4':
                    unique_formats[height] = f
            return {
                'title': info.get('title', 'Unknown'),
                'thumbnail': info.get('thumbnail', ''),
                'duration': info.get('duration', 0),
                'formats': sorted(unique_formats.values(), key=lambda x: x['height'], reverse=True)
            }
    except Exception as e:
        raise Exception(f"获取视频信息失败: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/info', methods=['POST'])
def info():
    """AJAX接口：获取视频信息"""
    url = request.form.get('url', '').strip()
    if not url:
        return jsonify({'error': '请输入YouTube链接'}), 400
    if not is_youtube_url(url):
        return jsonify({'error': '请提供有效的YouTube链接'}), 400
    
    try:
        video_info = get_video_info(url)
        return jsonify(video_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    """下载视频/音频的核心接口"""
    url = request.form.get('url', '').strip()
    download_type = request.form.get('type', 'video')  # 'video' or 'audio'
    format_id = request.form.get('format_id', '')  # 特定格式ID（可选）
    
    if not url:
        return "请输入YouTube链接", 400
    if not is_youtube_url(url):
        return "请提供有效的YouTube链接", 400
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp(prefix='ytdl_')
    
    # 配置yt-dlp参数
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,  # 只下载单个视频
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'restrictfilenames': True,
    }
    
    # 根据下载类型配置格式
    if download_type == 'audio':
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:  # video
        if format_id:
            # 使用用户选择的具体格式ID
            ydl_opts['format'] = format_id
        else:
            # 默认：选择最佳质量的mp4（视频+音频合并），如果没有则选择最佳整体
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    
    # 添加进度钩子（可选，用于日志）
    def progress_hook(d):
        if d['status'] == 'downloading':
            # 可以在这里记录进度，但不向前端推送
            pass
    ydl_opts['progress_hooks'] = [progress_hook]
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # 获取下载后的文件路径
            if 'requested_downloads' in info and info['requested_downloads']:
                filepath = info['requested_downloads'][0]['filepath']
            else:
                # 兼容性：查找临时目录下的文件
                files = list(Path(temp_dir).glob('*'))
                if not files:
                    raise Exception("未找到下载的文件")
                filepath = str(files[0])
            
            # 准备文件名（使用视频标题，替换不安全的字符）
            title = info.get('title', 'video')
            if download_type == 'audio':
                filename = f"{title}.mp3"
            else:
                ext = os.path.splitext(filepath)[1]
                filename = f"{title}{ext}"
            # 清理文件名中的非法字符
            filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            
            @after_this_request
            def cleanup(response):
                # 响应完成后删除临时目录
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    print(f"清理临时文件失败: {e}")
                return response
            
            # 发送文件
            return send_file(
                filepath,
                as_attachment=True,
                download_name=filename,
                mimetype='application/octet-stream'
            )
    except Exception as e:
        # 出错时也要清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)
        error_msg = f"下载失败: {str(e)}"
        # 常见错误提示
        if "ffmpeg" in str(e).lower():
            error_msg += " 服务器缺少ffmpeg组件，请尝试选择其他格式或联系管理员。"
        return error_msg, 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)