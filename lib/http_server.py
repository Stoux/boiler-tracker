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
base_url: str = ""  # Global variable to store the base URL

# In-memory storage for images
frames_images: Dict[str, bytes] = {}  # Annotated frames
frames_original_images: Dict[str, bytes] = {}  # Original frames
frequency_images: Dict[str, bytes] = {}  # Annotated frequency frames
frequency_original_images: Dict[str, bytes] = {}  # Original frequency frames

class BoilerHTTPHandler(BaseHTTPRequestHandler):
    def do_GET(self):
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
            self.serve_original_image('frequency', timestamp_str, index_str)
            return

        # Route for original standard frames
        frames_original_match = re.match(r'/images/frames/original/(\d+)-(\d+)\.jpg', self.path)
        if frames_original_match:
            timestamp_str, index_str = frames_original_match.groups()
            self.serve_original_image('frames', timestamp_str, index_str)
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

    def serve_original_image(self, image_type: str, timestamp_str: str, index_str: str):
        try:
            # Construct the image key
            image_key = f"{timestamp_str}-{index_str}.jpg"

            # Get the image data from the appropriate dictionary
            image_data = None
            if image_type == 'frames':
                image_data = frames_original_images.get(image_key)
            elif image_type == 'frequency':
                image_data = frequency_original_images.get(image_key)

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
            logger.error(f"Error serving original image: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

    def serve_grid_page(self):
        try:
            with status_lock:
                if not last_status or not last_timestamp:
                    self.send_response(404)
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b'No images available')
                    return

                timestamp_str = str(int(last_timestamp.timestamp()))

                # Generate HTML content
                html_content = """
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Boiler Images Grid</title>
                    <style>
                        body { font-family: Arial, sans-serif; margin: 20px; }
                        .grid-container { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
                        .grid-row { display: contents; }
                        .grid-item { text-align: center; }
                        img { max-width: 100%; border: 1px solid #ddd; }
                    </style>
                </head>
                <body>
                    <div class="grid-container">
                """

                # Add standard frames to the grid
                if last_status.frames:
                    for i in range(len(last_status.frames)):
                        # Use the global base_url for image URLs
                        original_url = f"{base_url}/images/frames/original/{timestamp_str}-{i}.jpg"
                        annotated_url = f"{base_url}/images/frames/{timestamp_str}-{i}.jpg"
                        html_content += f"""
                        <div class="grid-row">
                            <div class="grid-item">
                                <img src="{original_url}" alt="Original Frame {i}">
                            </div>
                            <div class="grid-item">
                                <img src="{annotated_url}" alt="Annotated Frame {i}">
                            </div>
                        </div>
                        """

                html_content += """
                    </div>
                </body>
                </html>
                """

                # Serve the HTML page
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(html_content.encode())
        except Exception as e:
            logger.error(f"Error serving grid page: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Server error: {str(e)}".encode())

def update_status(status: BoilerStatus, url_prefix: str = None):
    """Update the global status and timestamp, and store images in memory."""
    global last_status, last_timestamp, frames_images, frames_original_images, frequency_images, frequency_original_images, base_url

    # Update base_url if provided
    if url_prefix:
        base_url = url_prefix

    # Generate timestamp
    current_time = datetime.now(timezone.utc)
    timestamp_str = str(int(current_time.timestamp()))

    with status_lock:
        # Clear previous images from memory
        frames_images.clear()
        frames_original_images.clear()
        frequency_images.clear()
        frequency_original_images.clear()

        # Update global variables
        last_status = status
        last_timestamp = current_time

        # Store standard frames in memory
        if status.frames:
            for i, frame_data in enumerate(status.frames):
                # Store both original and annotated frames
                image_key = f"{timestamp_str}-{i}.jpg"

                # Convert annotated frame to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.annotated_frame)
                if is_success:
                    frames_images[image_key] = buffer.tobytes()

                # Convert original frame to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.original_frame)
                if is_success:
                    frames_original_images[image_key] = buffer.tobytes()

        # Store frequency frames in memory if available
        if status.frequency_frames:
            for i, frame_data in enumerate(status.frequency_frames):
                # Store both original and annotated frames
                image_key = f"{timestamp_str}-{i}.jpg"

                # Convert annotated frame to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.annotated_frame)
                if is_success:
                    frequency_images[image_key] = buffer.tobytes()

                # Convert original frame to bytes
                is_success, buffer = cv2.imencode(".jpg", frame_data.original_frame)
                if is_success:
                    frequency_original_images[image_key] = buffer.tobytes()

def get_image_urls(base_url: str) -> Dict[str, List[str]]:
    """Generate URLs for the latest images."""
    with status_lock:
        if not last_status or not last_timestamp:
            return {"frames": [], "frequency_frames": [], "frames_original": [], "frequency_frames_original": []}

        timestamp_str = str(int(last_timestamp.timestamp()))

        # Generate URLs for standard frames (annotated versions)
        frame_urls = []
        frame_original_urls = []
        if last_status.frames:
            for i in range(len(last_status.frames)):
                frame_urls.append(f"{base_url}/images/frames/{timestamp_str}-{i}.jpg")
                frame_original_urls.append(f"{base_url}/images/frames/original/{timestamp_str}-{i}.jpg")

        # Generate URLs for frequency frames (annotated versions)
        frequency_urls = []
        frequency_original_urls = []
        if last_status.frequency_frames:
            for i in range(len(last_status.frequency_frames)):
                frequency_urls.append(f"{base_url}/images/frequency/{timestamp_str}-{i}.jpg")
                frequency_original_urls.append(f"{base_url}/images/frequency/original/{timestamp_str}-{i}.jpg")

        # Add grid view URL
        grid_url = f"{base_url}/images/grid"

        return {
            "frames": frame_urls,
            "frames_original": frame_original_urls,
            "frequency_frames": frequency_urls,
            "frequency_frames_original": frequency_original_urls,
            "grid": [grid_url]
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
