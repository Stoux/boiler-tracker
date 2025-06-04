import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import cv2
import re
from loguru import logger
from typing import Optional, Dict, List, Tuple, ByteString
import io

from lib.analyze import BoilerStatus

# Global variables to store the last status and timestamp
last_status: Optional[BoilerStatus] = None
last_timestamp: Optional[datetime] = None
status_lock = threading.Lock()

# In-memory storage for images
frames_images: Dict[str, bytes] = {}
frequency_images: Dict[str, bytes] = {}

class BoilerHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
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

        # Default response for unknown routes
        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Not Found')

    def serve_image(self, image_type: str, timestamp_str: str, index_str: str):
        try:
            # Construct the image key
            image_key = f"{timestamp_str}-{index_str}.jpg"

            # Get the image data from the appropriate dictionary
            image_data = None
            if image_type == 'frames':
                image_data = frames_images.get(image_key)
            elif image_type == 'frequency':
                image_data = frequency_images.get(image_key)

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
            logger.error(f"Error serving image: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

def update_status(status: BoilerStatus):
    """Update the global status and timestamp, and store images in memory."""
    global last_status, last_timestamp, frames_images, frequency_images

    # Generate timestamp
    current_time = datetime.now(timezone.utc)
    timestamp_str = str(int(current_time.timestamp()))

    with status_lock:
        # Clear previous images from memory
        frames_images.clear()
        frequency_images.clear()

        # Update global variables
        last_status = status
        last_timestamp = current_time

        # Store standard frames in memory
        if status.frames:
            for i, frame_data in enumerate(status.frames):
                # Only store annotated frames
                image_key = f"{timestamp_str}-{i}.jpg"
                # Convert OpenCV image to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.annotated_frame)
                if is_success:
                    frames_images[image_key] = buffer.tobytes()

        # Store frequency frames in memory if available
        if status.frequency_frames:
            for i, frame_data in enumerate(status.frequency_frames):
                # Only store annotated frames
                image_key = f"{timestamp_str}-{i}.jpg"
                # Convert OpenCV image to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.annotated_frame)
                if is_success:
                    frequency_images[image_key] = buffer.tobytes()

def get_image_urls(base_url: str) -> Dict[str, List[str]]:
    """Generate URLs for the latest images."""
    with status_lock:
        if not last_status or not last_timestamp:
            return {"frames": [], "frequency_frames": []}

        timestamp_str = str(int(last_timestamp.timestamp()))

        # Generate URLs for standard frames (only annotated versions)
        frame_urls = []
        if last_status.frames:
            for i in range(len(last_status.frames)):
                frame_urls.append(f"{base_url}/images/frames/{timestamp_str}-{i}.jpg")

        # Generate URLs for frequency frames (only annotated versions)
        frequency_urls = []
        if last_status.frequency_frames:
            for i in range(len(last_status.frequency_frames)):
                frequency_urls.append(f"{base_url}/images/frequency/{timestamp_str}-{i}.jpg")

        return {
            "frames": frame_urls,
            "frequency_frames": frequency_urls
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
