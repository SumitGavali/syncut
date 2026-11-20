import threading
import time
import webview
import sys
import os

# Add the current directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from synccut.api.factory import create_app

def start_server():
    os.environ["SYNCCUT_DESKTOP"] = "1"
    app = create_app()
    # Disable reloader and debug for production
    app.run(host='127.0.0.1', port=5000, threaded=True, use_reloader=False, debug=False)

if __name__ == '__main__':
    print("Starting SyncCut Studio Desktop...")
    
    # Start Flask in a background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for Flask to boot up
    time.sleep(2)

    # Create the native desktop window
    window = webview.create_window(
        'SyncCut Studio', 
        'http://127.0.0.1:5000', 
        width=1440, 
        height=900,
        min_size=(1024, 768),
        background_color='#0a0a0c'
    )
    
    # Start the window loop
    webview.start()