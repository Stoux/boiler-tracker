import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import re
from loguru import logger
from typing import Optional, Dict, List

from lib.analyze import BoilerStatus
from lib.history import StatusHistory, HistoricalImageSet
from lib.http.pages.grid import serve_grid_page as generate_grid_page
from lib.http.pages.history import serve_history_page as generate_history_page

# Global variables to store the last status and timestamp
status_lock = threading.Lock()
base_url: str = ""  # Global variable to store the base URL

# Create a history of boiler statuses
status_history = StatusHistory(max_size=50)


class BoilerHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Route for history view
        if self.path == '/images/history':
            self.serve_history_page()
            return

        # Route for grid view
        if self.path == '/images/grid':
            self.serve_grid_page()
            return

        # Route for frequency frames
        frequency_match = re.match(r'/images/frequency/(\d+)-(\d+)\.jpg', self.path)
        if frequency_match:
            timestamp_str, index_str = frequency_match.groups()
            self.serve_image('frequency', timestamp_str, index_str)
            return

        # Route for standard frames
        frames_match = re.match(r'/images/frames/(\d+)-(\d+)\.jpg', self.path)
        if frames_match:
            timestamp_str, index_str = frames_match.groups()
            self.serve_image('frames', timestamp_str, index_str)
            return

        # Route for original frequency frames
        frequency_original_match = re.match(r'/images/frequency/original/(\d+)-(\d+)\.jpg', self.path)
        if frequency_original_match:
            timestamp_str, index_str = frequency_original_match.groups()
            self.serve_image('frequency', timestamp_str, index_str, is_original=True)
            return

        # Route for original standard frames
        frames_original_match = re.match(r'/images/frames/original/(\d+)-(\d+)\.jpg', self.path)
        if frames_original_match:
            timestamp_str, index_str = frames_original_match.groups()
            self.serve_image('frames', timestamp_str, index_str, is_original=True)
            return

        # Default response for unknown routes
        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Not Found')

    def serve_image(self, image_type: str, timestamp_str: str, index_str: str, is_original: bool = False):
        try:
            # Find the status with that timestamp
            image_data = None
            status = status_history.get_by_timestamp(timestamp_str)
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

            # Check if the image exists in memory
            if not image_data:
                self.send_response(404)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'Image not found')
                return

            # Set content type for JPEG
            content_type = 'image/jpeg'

            # Serve the image from memory
            self.send_response(200)
            self.send_header('Content-type', content_type)
            self.end_headers()
            self.wfile.write(image_data)
        except Exception as e:
            logger.error(f"Error serving {'original ' if is_original else ''}image: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

    def serve_history_page(self):
        with status_lock:
            generate_history_page(self, status_history, base_url)

    def serve_grid_page(self):
        with status_lock:
            last_status = status_history.get_last()
            generate_grid_page(self, last_status, base_url)

def update_status(status: BoilerStatus, url_prefix: str = None) -> bool:
    """Update the global status and timestamp, and store images in memory."""
    global base_url, status_history

    # Update base_url if provided
    if url_prefix:
        base_url = url_prefix

    # Generate timestamp
    current_time = datetime.now(timezone.utc)
    timestamp_str = str(int(current_time.timestamp()))

    with status_lock:
        # Add status to history
        return status_history.add_status(status, current_time, timestamp_str)

def get_image_urls() -> Dict[str, List[str]]:
    """Generate URLs for the latest images."""
    global base_url

    with status_lock:
        last_status = status_history.get_last()

        if not last_status:
            return {"frames": [], "frequency_frames": [], "frames_original": [], "frequency_frames_original": []}

        timestamp_str = last_status.timestamp_str

        # Generate URLs for standard frames (annotated versions)
        frame_urls = []
        frame_original_urls = []
        for i in range(len(last_status.frames.annotated)):
            frame_urls.append(f"{base_url}/images/frames/{timestamp_str}-{i}.jpg")
            frame_original_urls.append(f"{base_url}/images/frames/original/{timestamp_str}-{i}.jpg")

        # Generate URLs for frequency frames (annotated versions)
        frequency_urls = []
        frequency_original_urls = []
        for i in range(len(last_status.frequency.annotated)):
            frequency_urls.append(f"{base_url}/images/frequency/{timestamp_str}-{i}.jpg")
            frequency_original_urls.append(f"{base_url}/images/frequency/original/{timestamp_str}-{i}.jpg")

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


def start_http_server(port: int = 8800) -> HTTPServer:
    """Start the HTTP server in a separate thread."""
    server_address = ('', port)
    httpd = HTTPServer(server_address, BoilerHTTPHandler)

    # Start the server in a separate thread
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    logger.info(f"[HTTP] Server started on port {port}")
    return httpd
