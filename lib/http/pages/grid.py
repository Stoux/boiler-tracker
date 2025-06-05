from datetime import datetime
from typing import Optional
from http.server import BaseHTTPRequestHandler
from loguru import logger

from lib.history import HistoricalStatus


def serve_grid_page(handler: BaseHTTPRequestHandler, last_status: Optional[HistoricalStatus], base_url: str):
    """
    Serve a grid page showing original and annotated frames side by side.

    Args:
        handler: The HTTP request handler
        last_status: The last boiler status
        base_url: The base URL for image links
    """
    try:
        if not last_status:
            handler.send_response(404)
            handler.send_header('Content-type', 'text/plain')
            # Add no-cache headers
            handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            handler.send_header('Pragma', 'no-cache')
            handler.send_header('Expires', '0')
            handler.end_headers()
            handler.wfile.write(b'No images available')
            return

        timestamp_str = last_status.timestamp_str

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
            for i in range(len(last_status.frames.annotated)):
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
        handler.send_response(200)
        handler.send_header('Content-type', 'text/html')
        # Add no-cache headers
        handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        handler.send_header('Pragma', 'no-cache')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(html_content.encode())
    except Exception as e:
        logger.error(f"Error serving grid page: {e}")
        handler.send_response(500)
        handler.send_header('Content-type', 'text/plain')
        # Add no-cache headers
        handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        handler.send_header('Pragma', 'no-cache')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(f"Server error: {str(e)}".encode())
