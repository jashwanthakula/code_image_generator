import base64
import os
import uuid
from flask import Flask, render_template, request, Response, url_for, session, flash, redirect
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import Python3Lexer
from playwright.sync_api import sync_playwright, Error as PlaywrightError
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(16).hex())  # 32-char hex key (16 bytes)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # Max upload size: 1MB

# Default theme
THEME = "monokai"

# In-memory cache for screenshot data (keyed by UUID)
SCREENSHOT_CACHE = {}

# Custom Jinja2 filter for base64 encoding
@app.template_filter('b64encode')
def b64encode_filter(data):
    return base64.b64encode(data).decode('utf-8')

def generate_screenshot(code_content, filename):
    """Generate a high-quality screenshot in memory from code content."""
    try:
        with sync_playwright() as playwright:
            webkit = playwright.webkit
            browser = webkit.launch()
            browser_context = browser.new_context(
                device_scale_factor=3,  # Higher DPI for quality
                viewport={'width': 1280, 'height': 720}  # Initial larger viewport
            )
            page = browser_context.new_page()

            # Generate highlighted HTML
            formatter = HtmlFormatter(style=THEME)
            highlighted_code = highlight(code_content, Python3Lexer(), formatter)

            # Enhanced HTML with better styling
            html_content = f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Preview</title>
                <style>
                    {formatter.get_style_defs()}
                    .my_code {{
                        background-color: {formatter.style.background_color};
                        padding: 20px;
                        font-family: 'Courier New', Courier, monospace;
                        font-size: 16px;
                        line-height: 1.5;
                        white-space: pre-wrap;
                        border-radius: 8px;
                        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                        max-width: 1200px;
                        margin: 20px auto;
                    }}
                    body {{
                        margin: 0;
                        padding: 0;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                    }}
                </style>
            </head>
            <body>
                <div class="my_code">{highlighted_code}</div>
            </body>
            </html>
            """
            page.set_content(html_content)

            # Adjust viewport to fit content
            element = page.locator(".my_code")
            page.set_viewport_size({
                "width": min(1280, element.bounding_box()['width'] + 40),
                "height": min(720, element.bounding_box()['height'] + 40)
            })

            # Capture high-quality screenshot
            screenshot_bytes = element.screenshot(type="png")
            browser.close()

            return screenshot_bytes, f"{filename.rsplit('.', 1)[0]}_code_image.png"
    except PlaywrightError as e:
        if "Executable doesn't exist" in str(e):
            raise RuntimeError("Playwright browser binaries are missing. Please ensure 'playwright install' is run during deployment.")
        raise RuntimeError(f"Failed to generate screenshot: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Failed to generate screenshot: {str(e)}")

@app.route("/", methods=["GET", "POST"])
def index():
    # Initialize variables
    image_data = None
    image_filename = None
    cache_id = None

    # Handle GET request
    if request.method == "GET":
        # Check if this is a fresh GET (not a redirect after POST)
        is_redirect = session.pop('is_redirect', False)
        cache_id = session.get('cache_id')
        
        if not is_redirect and cache_id and cache_id in SCREENSHOT_CACHE:
            # Clear cache and session on manual refresh
            session.pop('cache_id', None)
            SCREENSHOT_CACHE.clear()
        elif cache_id and cache_id in SCREENSHOT_CACHE:
            # Load image data if this is a redirected GET
            image_data = SCREENSHOT_CACHE[cache_id]['bytes']
            image_filename = SCREENSHOT_CACHE[cache_id]['filename']

        return render_template("index.html", image_data=image_data, image_filename=image_filename, cache_id=cache_id)

    # Handle POST request
    if request.method == "POST":
        # Clear previous session and cache data
        session.pop('cache_id', None)
        session.pop('is_redirect', None)
        SCREENSHOT_CACHE.clear()

        # Validate file presence
        if 'code_file' not in request.files:
            flash("No file uploaded.", "danger")
            return render_template("index.html")

        file = request.files['code_file']
        if file.filename == '':
            flash("No file selected.", "danger")
            return render_template("index.html")

        # Check file size before reading
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        if file_size > app.config['MAX_CONTENT_LENGTH']:
            flash(f"File too large. Maximum size is {app.config['MAX_CONTENT_LENGTH'] // 1024} KB.", "danger")
            return render_template("index.html")
        file.seek(0)  # Reset file pointer

        # Secure filename
        filename = secure_filename(file.filename)

        # Read and process file content
        try:
            code_content = file.read().decode("utf-8")
        except UnicodeDecodeError:
            flash("Invalid file encoding. Please upload a UTF-8 encoded text file.", "danger")
            return render_template("index.html")
        except Exception as e:
            flash(f"Error reading file: {str(e)}", "danger")
            return render_template("index.html")

        # Generate screenshot
        try:
            screenshot_bytes, image_filename = generate_screenshot(code_content, filename)
            cache_id = str(uuid.uuid4())
            SCREENSHOT_CACHE[cache_id] = {
                'bytes': screenshot_bytes,
                'filename': image_filename
            }
            session['cache_id'] = cache_id  # Store only the cache ID
            session['is_redirect'] = True  # Set redirect flag
            # Redirect to GET to avoid resubmission prompt
            return redirect(url_for('index'))
        except RuntimeError as e:
            flash(str(e), "danger")
            return render_template("index.html")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "danger")
            return render_template("index.html")

@app.route("/download", methods=["GET"])
def download_image():
    """Serve the image for download from cache."""
    cache_id = session.get('cache_id')

    if not cache_id or cache_id not in SCREENSHOT_CACHE:
        flash("No image available for download. Please generate an image first.", "danger")
        return redirect(url_for('index'))

    screenshot_data = SCREENSHOT_CACHE[cache_id]
    screenshot_bytes = screenshot_data['bytes']
    image_filename = screenshot_data['filename']

    try:
        response = Response(
            screenshot_bytes,
            mimetype="image/png",
            headers={"Content-Disposition": f"attachment; filename={image_filename}"}
        )
        SCREENSHOT_CACHE.pop(cache_id, None)  # Clean up cache
        session.pop('cache_id', None)
        session.pop('is_redirect', None)
        return response
    except Exception as e:
        flash(f"Error serving download: {str(e)}", "danger")
        return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)