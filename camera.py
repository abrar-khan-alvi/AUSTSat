# rpi_camera.py
from picamera import PiCamera
from time import sleep

camera = PiCamera()

def capture_photo(filename="image.jpg", preview_time=3):
    """
    Captures a photo with a short preview.
    :param filename: Name of the file to save (default: image.jpg)
    :param preview_time: Time to show preview before capturing
    """
    filename = "image.jpg"
    camera.start_preview()
    sleep(2)
    camera.capture(filename)
    camera.stop_preview()
    print(f"Photo captured and saved as {filename}")
    return filename

def live_preview(duration=10):
    """
    Shows a live camera preview for a set duration.
    :param duration: Duration in seconds (default: 10)
    """
    try:
        camera.start_preview()
        print(f"Live preview started for {duration} seconds...")
        sleep(duration)
        camera.stop_preview()
        print("Preview ended.")
    except Exception as e:
        print(f"Error during preview: {e}")