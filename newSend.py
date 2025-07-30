from RF24 import RF24
from PIL import Image
import time
import camera
from sense import read_environmental_data, read_motion_data  # Ensure this is defined
import uuid
import os

radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

# ---------- Handshake ----------
radio.write(b'SYNC')
print("📡 Sent SYNC, waiting for ACK...")
time.sleep(1)

radio.startListening()
start = time.time()
while time.time() - start < 3:
    if radio.available():
        response = radio.read(radio.getDynamicPayloadSize())
        if response == b'ACK':
            print("🤝 ACK received, starting data loop.")
            break
radio.stopListening()

# ---------- Continuous Loop ----------
while True:
    # --- Read and Send Sensor Data ---
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    env = read_environmental_data()
    motion = read_motion_data()

    sensor_text = (
        f"{timestamp}|"
        f"T:{env['temperature']}C|H:{env['humidity']}%|P:{env['pressure']}hPa|"
        f"Pitch:{motion['orientation']['pitch']}|Roll:{motion['orientation']['roll']}|Yaw:{motion['orientation']['yaw']}|"
        f"Ax:{motion['accel_raw']['x']}|Ay:{motion['accel_raw']['y']}|Az:{motion['accel_raw']['z']}|"
        f"Gx:{motion['gyro_raw']['x']}|Gy:{motion['gyro_raw']['y']}|Gz:{motion['gyro_raw']['z']}|"
        f"Compass:{motion['compass']}"
    )

    sensor_bytes = sensor_text.encode()

    # Send sensor prefix
    radio.write(b'SENS')
    time.sleep(0.01)

    # Chunk sensor data
    chunk_size = 32
    chunks = [sensor_bytes[i:i + chunk_size] for i in range(0, len(sensor_bytes), chunk_size)]

    # Send number of chunks
    radio.write(len(chunks).to_bytes(1, 'big'))
    time.sleep(0.01)

    # Send each chunk
    for i, chunk in enumerate(chunks):
        if len(chunk) < chunk_size:
            chunk += b'\x00' * (chunk_size - len(chunk))
        radio.write(chunk)
        print(f"Sent sensor chunk {i+1}/{len(chunks)}")
        time.sleep(0.01)

    # --- Capture & Compress Image ---
    filename = camera.capture_photo("image.jpg")
    img = Image.open(filename).convert("RGB").resize((2048, 2048))
    jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
    img.save(jpeg_filename, format="JPEG", quality=50)

    with open(jpeg_filename, "rb") as f:
        jpeg_bytes = f.read()
    os.remove(jpeg_filename)

    print(f"📦 JPEG size: {len(jpeg_bytes)} bytes")

    # --- Send Image Metadata ---
    radio.write(b'IMAG')
    time.sleep(0.01)
    radio.write(len(jpeg_bytes).to_bytes(4, 'big'))
    time.sleep(0.01)

    # --- Send Image in 32-byte Chunks ---
    chunks = [jpeg_bytes[i:i+chunk_size] for i in range(0, len(jpeg_bytes), chunk_size)]

    for i, chunk in enumerate(chunks):
        if len(chunk) < chunk_size:
            chunk += b'\x00' * (chunk_size - len(chunk))
        radio.write(chunk)
        print(f"📤 Sent chunk {i+1}/{len(chunks)}")
        time.sleep(0.015)

    print("✅ Compressed image sent.")
    time.sleep(10)  # Add a delay to avoid overwhelming the receiver
