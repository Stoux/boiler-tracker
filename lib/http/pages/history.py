from datetime import datetime
from typing import Optional
from http.server import BaseHTTPRequestHandler
from loguru import logger
from zoneinfo import ZoneInfo

from lib.analyze import BoilerStatus
from lib.history import StatusHistory

def serve_history_page(handler: BaseHTTPRequestHandler, status_history: StatusHistory|None, base_url: str, show_saved: bool = False, saved_entries = None):
    """
    Serve a history page showing historical boiler statuses.

    Args:
        handler: The HTTP request handler
        status_history: The history of boiler statuses
        base_url: The base URL for image links
        show_saved: Whether to show saved entries from disk
        saved_entries: List of saved entries from disk (if show_saved is True)
    """
    try:
        # Determine which history to display
        if show_saved and saved_entries:
            history = saved_entries
            source_text = "Showing saved entries from disk"
            toggle_text = "Show entries from memory"
            toggle_url = f"{base_url}/images/history"
        elif status_history is not None:
            history = status_history.get_history()
            source_text = "Showing entries from memory"
            toggle_text = "Show saved entries from disk"
            toggle_url = f"{base_url}/images/history?show_saved=1"
        else:
            history = []
            source_text = "No entries available"
            toggle_text = "Show entries from memory"
            toggle_url = f"{base_url}/images/history"

        if not history:
            handler.send_response(404)
            handler.send_header('Content-type', 'text/plain')
            # Add no-cache headers
            handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            handler.send_header('Pragma', 'no-cache')
            handler.send_header('Expires', '0')
            handler.end_headers()
            handler.wfile.write(b'No history available')
            return

        # Generate HTML content
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Boiler Status History</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .status-container {{ margin-bottom: 30px; border: 1px solid #ddd; padding: 15px; border-radius: 5px; }}
                .status-header {{ display: flex; justify-content: space-between; margin-bottom: 15px; }}
                .status-info {{ flex: 1; }}
                .status-timestamp {{ font-weight: bold; }}
                .status-details {{ margin-bottom: 10px; }}
                .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
                .grid-row {{ display: contents; }}
                .grid-item {{ text-align: center; }}
                img {{ max-width: 100%; border: 1px solid #ddd; }}
                .heating-on {{ color: green; }}
                .heating-off {{ color: red; }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    background-color: #4CAF50;
                    color: white;
                    text-align: center;
                    text-decoration: none;
                    font-size: 16px;
                    margin: 10px 0;
                    cursor: pointer;
                    border: none;
                    border-radius: 4px;
                }}
                .button:hover {{
                    background-color: #45a049;
                }}
                .source-indicator {{
                    display: inline-block;
                    padding: 5px 10px;
                    border-radius: 4px;
                    background-color: #5bc0de;
                    color: white;
                    margin-right: 10px;
                }}
            </style>
        </head>
        <body>
            <h1>Boiler Status History</h1>
            <div style="margin-bottom: 20px;">
                <span class="source-indicator">{source_text}</span>
                <a href="{toggle_url}" class="button">{toggle_text}</a>
            </div>
        """

        # Add each status to the page
        for historical_status in history:
            timestamp = historical_status.timestamp
            timestamp_str = historical_status.timestamp_str

            # Convert timestamp to Europe/Amsterdam timezone and format for display
            amsterdam_time = timestamp.astimezone(ZoneInfo("Europe/Amsterdam"))
            formatted_time = amsterdam_time.strftime("%Y-%m-%d %H:%M:%S %Z")

            # Create status container
            html_content += f"""
            <div class="status-container">
                <div class="status-header">
                    <div class="status-info">
                        <div class="status-timestamp">Timestamp: {formatted_time}</div>
                        <div class="status-details">
                            <span>Lights: {historical_status.lights_on}</span> | 
                            <span class="{'heating-on' if historical_status.heating else 'heating-off'}">
                                Heating: {'Yes' if historical_status.heating else 'No'}
                            </span> | 
                            <span>General Light: {'On' if historical_status.general_light_on else 'Off'}</span> | 
                            <a href="{base_url}/images/grid?timestamp={timestamp_str}" target="_blank">View all frames</a>
                        </div>
                    </div>
                </div>
            """

            # Add frequency frames to the grid if available
            if historical_status.frequency.original:
                html_content += """
                <div class="grid-container">
                """

                for i in range(len(historical_status.frequency.original)):
                    # Use the global base_url for image URLs
                    original_url = f"{base_url}/images/frequency/original/{timestamp_str}-{i}.jpg"
                    annotated_url = f"{base_url}/images/frequency/{timestamp_str}-{i}.jpg"
                    html_content += f"""
                    <div class="grid-row">
                        <div class="grid-item">
                            <img src="{original_url}" alt="Original Frequency Frame {i}">
                        </div>
                        <div class="grid-item">
                            <img src="{annotated_url}" alt="Annotated Frequency Frame {i}">
                        </div>
                    </div>
                    """

                html_content += """
                </div>
                """
            else:
                html_content += "<p>No frequency frames available for this status.</p>"

            html_content += """
            </div>
            """

        html_content += """
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
        logger.error(f"Error serving history page: {e}")
        handler.send_response(500)
        handler.send_header('Content-type', 'text/plain')
        # Add no-cache headers
        handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        handler.send_header('Pragma', 'no-cache')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(f"Server error: {str(e)}".encode())
