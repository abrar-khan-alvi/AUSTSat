from RF24 import RF24
from PIL import Image
import time
import camera
from sense import read_environmental_data, read_motion_data
import uuid
import os

# --- Radio Setup ---
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # Use RF24_PA_MAX for range
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

# --- NEW: Reliable Send Function ---
def send_reliably(payload, expected_ack, retries=5, timeout=0.25):
    """
    Sends a payload and waits for a specific ACK.
    Returns True on success, False on failure.
    """
    for _ in range(retries):
        radio.write(payload)
        
        radio.startListening()
        start_time = time.time()
        while time.time() - start_time < timeout:
            if radio.available():
                response = radio.read(radio.getDynamicPayloadSize())
                if response == expected_ack:
                    radio.stopListening()
                    return True # Success!
        
        # If we get here, it was a timeout
        radio.stopListening()
        print(f"  ...ACK timeout for {payload[:10]}..., retrying.")
    
    return False # Failed after all retries

# ---------- 1. Handshake ----------
print("📡 Attempting handshake...")
if not send_reliably(b'SYNC', b'ACK_SYNC'):
    print("❌ Handshake failed. Exiting.")
    exit()
print("🤝 Handshake complete.")

# ---------- 2. Read and Send Sensor Data ----------
# (Sensor data reading part is the same)
timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
env = read_environmental_data()
motion = read_motion_data()
sensor_text = (f"{timestamp}|T:{env['temperature']}C|H:{env['humidity']}%|P:{env['pressure']}hPa|"
               f"Pitch:{motion['orientation']['pitch']}|Roll:{motion['orientation']['roll']}|Yaw:{motion['orientation']['yaw']}|"
               f"Ax:{motion['accel_raw']['x']}|Ay:{motion['accel_raw']['y']}|Az:{motion['accel_raw']['z']}|"
               f"Gx:{motion['gyro_raw']['x']}|Gy:{motion['gyro_raw']['y']}|Gz:{motion['gyro_raw']['z']}|Compass:{motion['compass']}")
sensor_bytes = sensor_text.encode()
sensor_chunks = [sensor_bytes[i:i + 32] for i in range(0, len(sensor_bytes), 32)]

print("\n✉️ Sending Sensor Data...")
if send_reliably(b'SENS' + len(sensor_chunks).to_bytes(1, 'big'), b'ACK_SENS_META'):
    for i, chunk in enumerate(sensor_chunks):
        if not send_reliably(chunk, f"S_ACK{i}".encode()):
            print(f"❌ Failed to send sensor chunk {i}. Aborting.")
            break
    else: # This 'else' runs if the loop completes without a 'break'
        print("✅ Sensor data sent and acknowledged.")
else:
    print("❌ Receiver did not acknowledge sensor metadata. Aborting sensor send.")
time.sleep(1)

# ---------- 3. Capture & Send Image ----------
# (Image capture and compress part is the same)
filename = camera.capture_photo("image.jpg")
img = Image.open(filename).convert("RGB").resize((160, 120)) # Keep size small for testing!
jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
img.save(jpeg_filename, format="JPEG", quality=50)
with open(jpeg_filename, "rb") as f:
    jpeg_bytes = f.read()
os.remove(jpeg_filename)

print(f"\n🖼️ Sending Image... Size: {len(jpeg_bytes)} bytes")
image_chunks = [jpeg_bytes[i:i + 32] for i in range(0, len(jpeg_bytes), 32)]

if send_reliably(b'IMAG' + len(jpeg_bytes).to_bytes(4, 'big'), b'ACK_IMAG_META'):
    for i, chunk in enumerate(image_chunks):
        print(f"  📤 Sending image chunk {i+1}/{len(image_chunks)}", end='\r')
        if not send_reliably(chunk, f"I_ACK{i}".encode()):
            print(f"\n❌ Failed to send image chunk {i}. Aborting.")
            break
    else:
        print("\n✅ Image sent and acknowledged.                     ")
else:
    print("❌ Receiver did not acknowledge image metadata. Aborting image send.")

print("\nMission Complete.")