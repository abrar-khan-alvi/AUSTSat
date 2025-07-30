from RF24 import RF24
from PIL import Image
import time
import camera  # Your camera library
from sense import read_environmental_data, read_motion_data  # Your sensor library
import uuid
import os

# --- Configuration ---
LOOP_INTERVAL_SECONDS = 60  # Wait 60 seconds between each capture/send cycle
IMAGE_QUALITY = 40          # JPEG quality (0-100), lower is smaller file size
IMAGE_RESOLUTION = (640, 480) # Resolution for the image

# --- Radio Setup (do this only once) ---
radio = RF24(22, 0)
if not radio.begin():
    raise RuntimeError("radio hardware not responding")

radio.setChannel(76)
radio.setPALevel(2, False) # For better range, consider RF24_PA_MAX
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening() # Set to transmitter mode

print("✅ Transmitter setup complete. Starting main loop.")

def perform_handshake():
    """Tries to handshake with the receiver. Returns True on success, False on failure."""
    radio.stopListening()
    radio.write(b'SYNC')
    print("📡 Sent SYNC, waiting for ACK...")

    # Switch to listening for the ACK
    radio.startListening()
    start_time = time.time()
    while time.time() - start_time < 2.0: # 2-second timeout
        if radio.available():
            response_len = radio.getDynamicPayloadSize()
            if response_len > 0:
                response = radio.read(response_len)
                if response == b'ACK':
                    print("🤝 ACK received. Proceeding with data transmission.")
                    radio.stopListening() # Go back to writing mode
                    return True
    
    print("❌ Handshake failed: No ACK received.")
    radio.stopListening() # Go back to writing mode
    return False


# --- Main Loop ---
while True:
    try:
        print(f"\n{'='*15} Starting New Cycle {'='*15}")

        # 1. Handshake with Receiver
        if not perform_handshake():
            print("Receiver not ready. Retrying after delay...")
            time.sleep(10) # Wait a bit longer if handshake fails
            continue # Skip to the next loop iteration

        # 2. Read and Send Sensor Data
        print("\n🌡️ Reading sensor data...")
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        env = read_environmental_data()
        motion = read_motion_data()

        sensor_text = (
            f"{timestamp}|"
            f"T:{env['temperature']:.1f}C|H:{env['humidity']:.1f}%|P:{env['pressure']:.1f}hPa|"
            f"Pitch:{motion['orientation']['pitch']:.1f}|Roll:{motion['orientation']['roll']:.1f}|Yaw:{motion['orientation']['yaw']:.1f}|"
            f"Ax:{motion['accel_raw']['x']:.2f}|Ay:{motion['accel_raw']['y']:.2f}|Az:{motion['accel_raw']['z']:.2f}|"
            f"Gx:{motion['gyro_raw']['x']:.2f}|Gy:{motion['gyro_raw']['y']:.2f}|Gz:{motion['gyro_raw']['z']:.2f}|"
            f"Compass:{motion['compass']:.1f}"
        )
        sensor_bytes = sensor_text.encode()

        print("📤 Sending sensor data...")
        radio.write(b'SENS')
        time.sleep(0.02) # Give receiver time to switch state

        # Chunk and send sensor data
        chunk_size = 32
        chunks = [sensor_bytes[i:i + chunk_size] for i in range(0, len(sensor_bytes), chunk_size)]
        radio.write(len(chunks).to_bytes(1, 'big'))
        time.sleep(0.02)

        for i, chunk in enumerate(chunks):
            radio.write(chunk) # The library handles padding if needed, but explicit padding is safer
            time.sleep(0.01)
        print("✅ Sensor data sent.")

        # 3. Capture, Compress, and Send Image
        print("\n📸 Capturing and processing image...")
        filename = camera.capture_photo("temp_capture.jpg")
        img = Image.open(filename).convert("RGB").resize(IMAGE_RESOLUTION)
        
        # Save to a temporary in-memory-like location if possible, or a temp file
        jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
        img.save(jpeg_filename, format="JPEG", quality=IMAGE_QUALITY)

        with open(jpeg_filename, "rb") as f:
            jpeg_bytes = f.read()
        os.remove(jpeg_filename) # Clean up temp file
        os.remove(filename)      # Clean up original capture

        print(f"📦 Compressed JPEG size: {len(jpeg_bytes)} bytes")

        print("📤 Sending image data...")
        radio.write(b'IMAG')
        time.sleep(0.02)
        radio.write(len(jpeg_bytes).to_bytes(4, 'big'))
        time.sleep(0.02)

        # Chunk and send image data
        image_chunks = [jpeg_bytes[i:i+chunk_size] for i in range(0, len(jpeg_bytes), chunk_size)]
        for i, chunk in enumerate(image_chunks):
            radio.write(chunk)
            # A small delay is crucial to not overwhelm the receiver
            time.sleep(0.015) 
            if (i+1) % 100 == 0: # Print progress every 100 chunks
                 print(f"-> Sent chunk {i+1}/{len(image_chunks)}")

        print(f"✅ Image sent successfully ({len(image_chunks)} chunks).")
        print(f"\n{'='*17} Cycle Complete {'='*17}")


    except Exception as e:
        print(f"\n❌❌❌ AN ERROR OCCURRED IN THE MAIN LOOP: {e} ❌❌❌")
        print("Attempting to continue after a delay...")

    finally:
        # 4. Wait for the next cycle
        print(f"🔄 Waiting for {LOOP_INTERVAL_SECONDS} seconds before next cycle...")
        time.sleep(LOOP_INTERVAL_SECONDS)
