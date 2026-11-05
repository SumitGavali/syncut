import os
import subprocess
import logging
from synccut.paths import get_ffmpeg_path

logger = logging.getLogger(__name__)

def generate_proxy(input_path: str, output_dir: str) -> str:
    """
    Generates a 720p H.264 proxy with a burned-in timecode.
    
    WHY: Editors cannot scrub raw 4K footage in a browser. We generate 
    a lightweight file for the web UI, while keeping the original for export.
    """
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, f"{base_name}_proxy.mp4")

    ffmpeg_bin = get_ffmpeg_path()

    # WHY this specific command? 
    # -vf "scale=-2:720": Scales height to 720p, width auto-computes to keep aspect ratio.
    # drawtext: Burns the timestamp (Hours:Minutes:Seconds) into the top left.
    # -c:v libx264 -preset veryfast: Uses CPU H.264 encoding, optimized for speed.
    # -crf 28: Constant Rate Factor. 28 is highly compressed (small file), perfect for proxies.
    # -c:a aac -b:a 128k: Converts audio to lightweight stereo AAC.
    command = [
        ffmpeg_bin,
        "-y", # Overwrite output if it exists
        "-i", input_path,
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        output_path
    ]

    logger.info(f"Starting proxy generation: {output_path}")
    
    try:
        # WHY: subprocess.run executes the FFmpeg binary. check=True raises an error if FFmpeg fails.
        result = subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True, 
            check=True
        )
        logger.info(f"Proxy generated successfully: {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr}")
        raise RuntimeError(f"Proxy generation failed: {e.stderr}")