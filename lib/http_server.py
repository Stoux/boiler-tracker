import threading
import os
import json
from datetime import datetime, timezone
import asyncio
from fastapi import FastAPI, Response, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
import hypercorn
from hypercorn.config import Config
from hypercorn.asyncio import serve
from loguru import logger
from typing import Optional, Dict, List, Any, Union
import cv2
import numpy as np
import io

from lib.analyze import BoilerStatus
from lib.history import StatusHistory, HistoricalImageSet, HistoricalStatus
from lib.http.pages.grid import serve_grid_page as generate_grid_page
from lib.http.pages.history import serve_history_page as generate_history_page
from lib.rwlock import RWLock

# Global variables (same as in the original implementation)
status_lock = RWLock()
base_url: str = ""
status_history = StatusHistory(max_size=50)
# Global variable to store the currently served HistoricalStatus entry
CachedHistoricalStatus: Optional[HistoricalStatus] = None

# Create FastAPI app
app = FastAPI(title="Boiler Tracker")

# Custom response class for serving images with cache headers
class ImageResponse(Response):
    def __init__(self, content, media_type="image/webp", *args, **kwargs):
        super().__init__(content, media_type=media_type, *args, **kwargs)
        # Allow caching for images with a max age of 1 day (86400 seconds)
        self.headers["Cache-Control"] = "public, max-age=86400"
        # Set an expiration date 1 day in the future
        from datetime import datetime, timedelta
        expiry_date = datetime.utcnow() + timedelta(days=1)
        self.headers["Expires"] = expiry_date.strftime("%a, %d %b %Y %H:%M:%S GMT")

# This class has been removed as part of the FastAPI/Hypercorn/asyncio implementation

# No-cache headers are now set directly in the page generation functions

# Routes
@app.get("/images/history")
async def history_page(show_saved: int = 0):
    # Variables to store data fetched under the lock
    saved_entries = None
    history_copy = None

    # Only hold the lock while fetching the data
    with status_lock.read_lock():
        if show_saved == 1:
            # Load all saved entries from disk
            saved_entries = load_all_snapshots_from_disk()
        else:
            # Make a copy of the status history to use outside the lock
            history_copy = status_history

    # Generate the page content outside the lock
    if show_saved == 1:
        content, status_code, headers = generate_history_page(None, base_url, True, saved_entries)
    else:
        content, status_code, headers = generate_history_page(history_copy, base_url, False)

    response = Response(content=content.encode() if isinstance(content, str) else content, 
                       status_code=status_code)
    response.headers.update(headers)
    return response

@app.get("/images/grid")
async def grid_page(timestamp: Optional[str] = None):
    global CachedHistoricalStatus

    # Variables to store data fetched under the lock
    status = None
    loaded_from_disk = False

    # Only hold the lock while fetching the data
    with status_lock.read_lock():
        # First check if we have a cached status with the requested timestamp
        if timestamp and CachedHistoricalStatus and CachedHistoricalStatus.timestamp_str == timestamp:
            status = CachedHistoricalStatus
            # Check if this was loaded from disk originally
            loaded_from_disk = not status_history.get_by_timestamp(timestamp)
        elif timestamp:
            # Get the status with the specified timestamp
            status = status_history.get_by_timestamp(timestamp)

            # If found in memory, cache it
            if status:
                CachedHistoricalStatus = status
            # If not in memory, check if it exists on disk
            else:
                status = load_snapshot_from_disk(timestamp)
                if status:
                    loaded_from_disk = True
                    # load_snapshot_from_disk already sets CachedHistoricalStatus
        else:
            # Get the last status if no timestamp is specified
            status = status_history.get_last()
            if status:
                CachedHistoricalStatus = status

    # Check if we have a valid status
    if not status:
        raise HTTPException(status_code=404, detail="No images available")

    # Generate the page content outside the lock
    content, status_code, headers = generate_grid_page(status, base_url, loaded_from_disk)

    response = Response(content=content.encode() if isinstance(content, str) else content, 
                       status_code=status_code)
    response.headers.update(headers)
    return response

@app.get("/images/save_snapshot/{timestamp_str}")
async def save_snapshot(timestamp_str: str):
    try:
        # Variable to store data fetched under the lock
        status = None

        # Only hold the lock while fetching the data
        with status_lock.read_lock():
            # Get the status with the specified timestamp
            status = status_history.get_by_timestamp(timestamp_str)

        if not status:
            raise HTTPException(status_code=404, detail="Status not found")

        # Create the directory if it doesn't exist
        save_dir = f"images/saved/{timestamp_str}"
        os.makedirs(save_dir, exist_ok=True)

        # Save frames
        if status.frames:
            # Save annotated frames
            for i, image_data in status.frames.annotated.items():
                with open(f"{save_dir}/frame_{i}_annotated.png", "wb") as f:
                    f.write(image_data)

            # Save original frames
            for i, image_data in status.frames.original.items():
                with open(f"{save_dir}/frame_{i}_original.png", "wb") as f:
                    f.write(image_data)

        # Save frequency frames if they exist
        if status.frequency:
            # Save annotated frequency frames
            for i, image_data in status.frequency.annotated.items():
                with open(f"{save_dir}/frequency_{i}_annotated.png", "wb") as f:
                    f.write(image_data)

            # Save original frequency frames
            for i, image_data in status.frequency.original.items():
                with open(f"{save_dir}/frequency_{i}_original.png", "wb") as f:
                    f.write(image_data)

        # Save info.json with all HistoricalStatus data
        info = {
            "heating": status.heating,
            "lights_on": status.lights_on,
            "general_light_on": status.general_light_on,
            "timestamp": status.timestamp.isoformat(),
            "timestamp_str": status.timestamp_str,
            "lower_green": status.lower_green.tolist() if status.lower_green is not None else None,
            "upper_green": status.upper_green.tolist() if status.upper_green is not None else None,
            "frames": {
                "annotated": [f"frame_{i}_annotated.png" for i in status.frames.annotated.keys()],
                "original": [f"frame_{i}_original.png" for i in status.frames.original.keys()]
            }
        }

        if status.frequency:
            info["frequency"] = {
                "annotated": [f"frequency_{i}_annotated.png" for i in status.frequency.annotated.keys()],
                "original": [f"frequency_{i}_original.png" for i in status.frequency.original.keys()]
            }

        with open(f"{save_dir}/info.json", "w") as f:
            json.dump(info, f, indent=2)

        # Redirect back to the grid page
        return RedirectResponse(url=f"{base_url}/images/grid?timestamp={timestamp_str}")

    except Exception as e:
        logger.error(f"Error saving snapshot: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/images/delete_snapshot/{timestamp_str}")
async def delete_snapshot(timestamp_str: str):
    try:
        save_dir = f"images/saved/{timestamp_str}"

        # Check if the directory exists
        if not os.path.exists(save_dir):
            raise HTTPException(status_code=404, detail="Snapshot not found")

        # Delete all files in the directory
        for filename in os.listdir(save_dir):
            file_path = os.path.join(save_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

        # Remove the directory
        os.rmdir(save_dir)

        # Redirect back to the history page with show_saved=1
        return RedirectResponse(url=f"{base_url}/images/history?show_saved=1")

    except Exception as e:
        logger.error(f"Error deleting snapshot: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.get("/images/frames/{timestamp_str}-{index_str}.webp")
@app.get("/images/frames/{timestamp_str}-{index_str}.png")  # Keep .png endpoint for backward compatibility
async def serve_frame(timestamp_str: str, index_str: str):
    image_data = get_image_data("frames", timestamp_str, index_str, False)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")
    # Convert PNG to WebP for better performance
    webp_data = convert_to_webp(image_data)
    return ImageResponse(content=webp_data)

@app.get("/images/frames/original/{timestamp_str}-{index_str}.webp")
@app.get("/images/frames/original/{timestamp_str}-{index_str}.png")  # Keep .png endpoint for backward compatibility
async def serve_original_frame(timestamp_str: str, index_str: str):
    image_data = get_image_data("frames", timestamp_str, index_str, True)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")
    # Convert PNG to WebP for better performance
    webp_data = convert_to_webp(image_data)
    return ImageResponse(content=webp_data)

@app.get("/images/frequency/{timestamp_str}-{index_str}.webp")
@app.get("/images/frequency/{timestamp_str}-{index_str}.png")  # Keep .png endpoint for backward compatibility
async def serve_frequency(timestamp_str: str, index_str: str):
    image_data = get_image_data("frequency", timestamp_str, index_str, False)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")
    # Convert PNG to WebP for better performance
    webp_data = convert_to_webp(image_data)
    return ImageResponse(content=webp_data)

@app.get("/images/frequency/original/{timestamp_str}-{index_str}.webp")
@app.get("/images/frequency/original/{timestamp_str}-{index_str}.png")  # Keep .png endpoint for backward compatibility
async def serve_original_frequency(timestamp_str: str, index_str: str):
    image_data = get_image_data("frequency", timestamp_str, index_str, True)
    if not image_data:
        raise HTTPException(status_code=404, detail="Image not found")
    # Convert PNG to WebP for better performance
    webp_data = convert_to_webp(image_data)
    return ImageResponse(content=webp_data)

# Helper functions
def convert_to_webp(image_data: bytes, quality: int = 80) -> bytes:
    """
    Convert PNG image data to WebP format with the specified quality.

    Args:
        image_data: PNG image data as bytes
        quality: WebP quality (0-100, higher is better quality but larger file size)

    Returns:
        WebP image data as bytes
    """
    try:
        # Convert bytes to numpy array
        nparr = np.frombuffer(image_data, np.uint8)
        # Decode the image
        img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)

        # Encode as WebP
        _, buffer = cv2.imencode('.webp', img, [cv2.IMWRITE_WEBP_QUALITY, quality])

        # Convert to bytes and return
        return buffer.tobytes()
    except Exception as e:
        logger.error(f"Error converting image to WebP: {e}")
        # Return original image data if conversion fails
        return image_data

def get_image_data(image_type: str, timestamp_str: str, index_str: str, is_original: bool = False) -> Optional[bytes]:
    try:
        global CachedHistoricalStatus

        # Find the status with that timestamp
        image_data = None

        # First check if we have a cached status with the same timestamp
        if CachedHistoricalStatus and CachedHistoricalStatus.timestamp_str == timestamp_str:
            status = CachedHistoricalStatus
        else:
            # If not in cache, get from status history
            status = status_history.get_by_timestamp(timestamp_str)
            if status:
                # Cache the status for future use
                CachedHistoricalStatus = status

        if status:
            image_set: Optional[HistoricalImageSet] = None
            if image_type == 'frames':
                image_set = status.frames
            elif image_type == 'frequency':
                image_set = status.frequency

            image_frames: Optional[Dict[str, bytes]] = None
            if image_set:
                if is_original:
                    image_frames = image_set.original
                else:
                    image_frames = image_set.annotated

            if image_frames:
                image_data = image_frames.get(index_str)

        # If not in memory, check if it exists on disk
        if not image_data:
            # Determine the file path based on the image type and whether it's original
            save_dir = f"images/saved/{timestamp_str}"
            if os.path.exists(save_dir):
                file_prefix = "frame" if image_type == 'frames' else "frequency"
                file_suffix = "original" if is_original else "annotated"
                file_path = f"{save_dir}/{file_prefix}_{index_str}_{file_suffix}.png"

                # Check if the file exists
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        image_data = f.read()

                    # If we don't have a cached status for this timestamp, load it from disk
                    if not CachedHistoricalStatus or CachedHistoricalStatus.timestamp_str != timestamp_str:
                        loaded_status = load_snapshot_from_disk(timestamp_str)
                        if loaded_status:
                            CachedHistoricalStatus = loaded_status

        return image_data

    except Exception as e:
        logger.error(f"Error getting image data: {e}")
        return None

def load_snapshot_from_disk(timestamp_str: str) -> Optional[HistoricalStatus]:
    """Load a snapshot from disk if it exists."""
    try:
        global CachedHistoricalStatus

        # First check if we already have this snapshot cached
        if CachedHistoricalStatus and CachedHistoricalStatus.timestamp_str == timestamp_str:
            return CachedHistoricalStatus

        save_dir = f"images/saved/{timestamp_str}"

        # Check if the directory exists
        if not os.path.exists(save_dir):
            return None

        # Check if info.json exists
        info_path = f"{save_dir}/info.json"
        if not os.path.exists(info_path):
            return None

        # Load info.json
        with open(info_path, "r") as f:
            info = json.load(f)

        # Create HistoricalImageSet for frames
        frames_annotated = {}
        frames_original = {}

        # Load annotated frames
        for i, frame_path in enumerate(info["frames"]["annotated"]):
            with open(f"{save_dir}/{frame_path}", "rb") as f:
                frames_annotated[str(i)] = f.read()

        # Load original frames
        for i, frame_path in enumerate(info["frames"]["original"]):
            with open(f"{save_dir}/{frame_path}", "rb") as f:
                frames_original[str(i)] = f.read()

        frames = HistoricalImageSet(annotated=frames_annotated, original=frames_original)

        # Create HistoricalImageSet for frequency frames if they exist
        frequency = None
        if "frequency" in info:
            frequency_annotated = {}
            frequency_original = {}

            # Load annotated frequency frames
            for i, frame_path in enumerate(info["frequency"]["annotated"]):
                with open(f"{save_dir}/{frame_path}", "rb") as f:
                    frequency_annotated[str(i)] = f.read()

            # Load original frequency frames
            for i, frame_path in enumerate(info["frequency"]["original"]):
                with open(f"{save_dir}/{frame_path}", "rb") as f:
                    frequency_original[str(i)] = f.read()

            frequency = HistoricalImageSet(annotated=frequency_annotated, original=frequency_original)

        # Convert lower_green and upper_green back to numpy arrays if they exist
        import numpy as np
        lower_green = np.array(info["lower_green"]) if info["lower_green"] is not None else None
        upper_green = np.array(info["upper_green"]) if info["upper_green"] is not None else None

        # Create HistoricalStatus
        from datetime import datetime
        timestamp = datetime.fromisoformat(info["timestamp"])

        historical_status = HistoricalStatus(
            heating=info["heating"],
            lights_on=info["lights_on"],
            general_light_on=info["general_light_on"],
            timestamp=timestamp,
            timestamp_str=info["timestamp_str"],
            frames=frames,
            frequency=frequency,
            lower_green=lower_green,
            upper_green=upper_green
        )

        # Cache the loaded status
        CachedHistoricalStatus = historical_status

        return historical_status

    except Exception as e:
        logger.error(f"Error loading snapshot from disk: {e}")
        return None

def load_all_snapshots_from_disk():
    """Load all snapshots from disk."""
    saved_entries = []

    # Check if the saved directory exists
    if not os.path.exists("images/saved"):
        return saved_entries

    # Get all subdirectories in the saved directory
    for timestamp_str in os.listdir("images/saved"):
        # Check if it's a directory
        if os.path.isdir(f"images/saved/{timestamp_str}"):
            # Load the snapshot (this will also cache it in CachedHistoricalStatus)
            snapshot = load_snapshot_from_disk(timestamp_str)
            if snapshot:
                saved_entries.append(snapshot)

    # Sort by timestamp (newest first)
    saved_entries.sort(key=lambda x: x.timestamp, reverse=True)

    # If we have entries, cache the most recent one
    if saved_entries:
        global CachedHistoricalStatus
        CachedHistoricalStatus = saved_entries[0]

    return saved_entries

# Functions that need to be maintained for compatibility
def update_status(status: BoilerStatus, url_prefix: str = None) -> bool:
    """Update the global status and timestamp, and store images in memory."""
    global base_url, status_history, CachedHistoricalStatus

    # Update base_url if provided
    if url_prefix:
        base_url = url_prefix

    # Generate timestamp
    current_time = datetime.now(timezone.utc)
    timestamp_str = str(int(current_time.timestamp()))

    with status_lock.write_lock():
        # Add status to history
        status_changed = status_history.add_status(status, current_time, timestamp_str)

        # Update the cached status to the latest one
        CachedHistoricalStatus = status_history.get_last()

        return status_changed

def get_image_urls() -> Dict[str, List[str]]:
    """Generate URLs for the latest images."""
    global base_url, CachedHistoricalStatus

    # Variable to store data fetched under the lock
    last_status = None

    # Only hold the lock while fetching the data
    with status_lock.read_lock():
        # First check if we have a cached status
        if CachedHistoricalStatus:
            last_status = CachedHistoricalStatus
        else:
            last_status = status_history.get_last()
            if last_status:
                CachedHistoricalStatus = last_status

    if not last_status:
        return {"frames": [], "frequency_frames": [], "frames_original": [], "frequency_frames_original": []}

    timestamp_str = last_status.timestamp_str

    # Generate URLs for standard frames (annotated versions)
    frame_urls = []
    frame_original_urls = []
    for i in range(len(last_status.frames.annotated)):
        frame_urls.append(f"{base_url}/images/frames/{timestamp_str}-{i}.png")
        frame_original_urls.append(f"{base_url}/images/frames/original/{timestamp_str}-{i}.png")

    # Generate URLs for frequency frames (annotated versions)
    frequency_urls = []
    frequency_original_urls = []
    for i in range(len(last_status.frequency.annotated)):
        frequency_urls.append(f"{base_url}/images/frequency/{timestamp_str}-{i}.png")
        frequency_original_urls.append(f"{base_url}/images/frequency/original/{timestamp_str}-{i}.png")

    # Add grid view URL
    grid_url = f"{base_url}/images/grid"

    # Add history view URL
    history_url = f"{base_url}/images/history"

    return {
        "frames": frame_urls,
        "frames_original": frame_original_urls,
        "frequency_frames": frequency_urls,
        "frequency_frames_original": frequency_original_urls,
        "grid": [grid_url],
        "history": [history_url]
    }

# Server class to maintain compatibility with the original interface
class HTTP3Server:
    def __init__(self, app, host, port):
        self.app = app
        self.host = host
        self.port = port
        self.server_task = None
        self.shutdown_event = asyncio.Event()

    def shutdown(self):
        """Shutdown the server."""
        if self.server_task:
            self.shutdown_event.set()
            logger.info("[HTTP] Server shutdown initiated")

def start_http_server(port: int = 8800) -> Any:
    """Start the HTTP server in a separate thread."""
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]
    config.alpn_protocols = ["h3", "h2", "http/1.1"]  # Support HTTP/3, HTTP/2, and HTTP/1.1

    server = HTTP3Server(app, "0.0.0.0", port)

    async def run_server():
        try:
            await serve(app, config, shutdown_trigger=server.shutdown_event.wait)
        except Exception as e:
            logger.error(f"[HTTP] Server error: {e}")

    # Start the server in a separate thread
    def start_async_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server.server_task = loop.create_task(run_server())
        loop.run_until_complete(server.server_task)

    server_thread = threading.Thread(target=start_async_server, daemon=True)
    server_thread.start()

    logger.info(f"[HTTP] Server started on port {port} with HTTP/3 support")
    return server
