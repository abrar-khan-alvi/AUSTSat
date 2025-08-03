# rpi_camera_updated.py
from picamera2 import Picamera2, Preview
import time

def capture_photo(filename="image.jpg", preview_time=3):
    """
    Captures a photo with a short preview.
    
    Args:
        filename (str): Name of the file to save.
        preview_time (int): Time in seconds to show the preview.
    """
    with Picamera2() as camera:
        preview_config = camera.create_preview_configuration()
        camera.configure(preview_config)
        
        camera.start_preview(Preview.QTGL)
        
        print(f"Preview for {preview_time} seconds...")
        time.sleep(preview_time)
        
        camera.capture_file(filename)
        print(f"Photo captured and saved as {filename}")
        
        camera.stop_preview()

def live_preview(duration=10):
    """
    Shows a live camera preview for a set duration.
    
    Args:
        duration (int): Duration of the preview in seconds.
    """
    with Picamera2() as camera:
        camera.start_preview(Preview.QTGL)
        
        print(f"Live preview for {duration} seconds...")
        try:
            time.sleep(duration)
        finally:
            camera.stop_preview()
            print("Preview ended.")

if __name__ == '__main__':
    # Example usage:
    # live_preview(15)
    # capture_photo("my_photo.jpg", 5)
    pass