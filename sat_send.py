import time
import uuid
import os
from RF24 import RF24
from PIL import Image
# --- MOCK FUNCTIONS for testing ---
# Replace these with your actual camera and sense hat libraries
def capture_photo(filename):
    """Mocks capturing a photo. Creates a dummy image."""
    try:
        from picamera import PiCamera
        with PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.start_preview()
            time.sleep(2) # Camera warm-up time
            camera.capture(filename)
            camera.stop_preview()
        print(f"Photo captured and saved to {filename}")
    except ImportError:
        print("picamera library not found. Creating a dummy image for testing.")
        dummy_img = Image.new('RGB', (640, 480), color = 'red')
        dummy_img.save(filename, 'JPEG')
    return filename

def read_environmental_data():
    """Mocks reading environmental data from Sense HAT."""
    try:
        from sense_hat import SenseHat
        sense = SenseHat()
        return {
            'temperature': round(sense.get_temperature(), 2),
            'humidity': round(sense.get_humidity(), 2),
            'pressure': round(sense.get_pressure(), 2),
        }
    except ImportError:
        print("sense_hat library not found. Using dummy environmental data.")
        return {'temperature': 25.5, 'humidity': 45.2, 'pressure': 1013.1}

def read_motion_data():
    """Mocks reading motion data from Sense HAT."""
    try:
        from sense_hat import SenseHat
        sense = SenseHat()
        o = sense.get_orientation()
        a = sense.get_accelerometer_raw()
        g = sense.get_gyroscope_raw()
        c = sense.get_compass_raw()
        return {
            'orientation': {'pitch': round(o['pitch'], 2), 'roll': round(o['roll'], 2), 'yaw': round(o['yaw'], 2)},
            'accel_raw': {'x': round(a['x'], 2), 'y': round(a['y'], 2), 'z': round(a['z'], 2)},
            'gyro_raw': {'x': round(g['x'], 2), 'y': round(g['y'], 2), 'z': round(g['z'], 2)},
            'compass': {'x': round(c['x'], 2), 'y': round(c['y'], 2), 'z': round(c['z'], 2)},
        }
    except ImportError:
        print("sense_hat library not found. Using dummy motion data.")
        return {
            'orientation': {'pitch': 10.1, 'roll': -5.2, 'yaw': 180.3},
            'accel_raw': {'x': 0.01, 'y': 0.02, 'z': 0.99},
            'gyro_raw': {'x': 0.1, 'y': -0.1, 'z': 0.0},
            'compass': {'x': 20.5, 'y':-15.2, 'z': 45.1}
        }
# --- END MOCK FUNCTIONS ---

# --- Radio Setup ---
# This is for a Raspberry Pi.
# CE Pin: GPIO22 (Pin 15)
# CSN Pin: GPIO8 (Pin 24, SPI CE0)
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2) # Use RF24_PA_MAX for nRF24L01+PA+LNA modules
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

def send_reliably(payload, ack_payload):
    """Sends a payload and waits for a specific ACK from the receiver."""
    radio.stopListening()
    retries = 5
    for i in range(retries):
        radio.write(payload)
        radio.startListening()
        start_time = time.time()
        while time.time() - start_time < 0.2: # 200ms timeout for ACK
            if radio.available():
                response = radio.read(radio.getDynamicPayloadSize())
                if response == ack_payload:
                    radio.stopListening()
                    return True # Success!
        radio.stopListening()
        print(f"Timeout waiting for {ack_payload.decode()}, retry {i+1}/{retries}")
    return False # Failed after all retries

# ---------- 1. Handshake ----------
print("Attempting handshake...")
if not send_reliably(b'SYNC', b'ACK'):
    print("Handshake failed. Aborting.")
    exit()
print("Handshake complete.")
time.sleep(1)

# ---------- 2. Read and Send Sensor Data (Fire-and-forget for speed) ----------
print("\n--- Sending Sensor Data ---")
timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
env = read_environmental_data()
motion = read_motion_data()

sensor_text = (
    f"{timestamp}|"
    f"T:{env['temperature']}C|H:{env['humidity']}%|P:{env['pressure']}hPa|"
    f"Pitch:{motion['orientation']['pitch']}|Roll:{motion['orientation']['roll']}|Yaw:{motion['orientation']['yaw']}"
)
sensor_bytes = sensor_text.encode()

radio.write(b'SENS')
time.sleep(0.01)

chunk_size = 32
chunks = [sensor_bytes[i:i + chunk_size] for i in range(0, len(sensor_bytes), chunk_size)]

radio.write(len(chunks).to_bytes(1, 'big'))
time.sleep(0.01)

for i, chunk in enumerate(chunks):
    if len(chunk) < chunk_size:
        chunk += b'\x00' * (chunk_size - len(chunk))
    radio.write(chunk)
    time.sleep(0.01)
print("Sensor data sent.")
time.sleep(1) # Give receiver time to process

# ---------- 3. RELIABLE IMAGE TRANSFER ----------
print("\n--- Starting Reliable Image Transfer ---")
# IMPORTANT: Use a SMALL image for testing this protocol!
filename = "image_to_send.jpg"
capture_photo(filename)
img = Image.open(filename).convert("RGB").resize((160, 120), Image.LANCZOS)
jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
img.save(jpeg_filename, format="JPEG", quality=40)

with open(jpeg_filename, "rb") as f:
    jpeg_bytes = f.read()
os.remove(jpeg_filename)
os.remove(filename)
print(f"Image size: {len(jpeg_bytes)} bytes")

# Announce image transfer
if not send_reliably(b'IMAG', b'ACK_IMAG'):
    print("Receiver did not acknowledge image request. Aborting.")
    exit()

# Send image size
size_payload = len(jpeg_bytes).to_bytes(4, 'big')
if not send_reliably(size_payload, b'ACK_SIZE'):
    print("Receiver did not acknowledge image size. Aborting.")
    exit()
print("Receiver ready for image data.")

# Send Image in Confirmed Chunks
chunks = [jpeg_bytes[i:i+chunk_size] for i in range(0, len(jpeg_bytes), chunk_size)]

for i, chunk in enumerate(chunks):
    ack_needed = f"ACK{i}".encode()
    print(f"Sending chunk {i+1}/{len(chunks)}...", end="\r")
    if not send_reliably(chunk, ack_needed):
        print(f"\nFAILED to send chunk {i+1}. Aborting transfer.")
        break
else:
    print(f"\nAll {len(chunks)} chunks sent and acknowledged!")
    if send_reliably(b'DONE', b'ACK_DONE'):
        print("✅✅✅ Transfer complete. ✅✅✅")
