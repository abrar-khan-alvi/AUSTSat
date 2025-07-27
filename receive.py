from RF24 import RF24
from PIL import Image
import time
import base64
import requests
import uuid
import os
import json

# Setup NRF24L01
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

# --- State variables ---
parsed_sensor_data = None # <-- CHANGE: We'll store the dictionary here
image_base64 = None
# sensor_json_filename is no longer needed

# ---------- Handshake ----------
print("📡 Waiting for handshake...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            radio.writeAckPayload(1, b'ACK')
            print("🤝 Handshake complete.")
            break

# ---------- Receive Loop ----------
while True:
    if radio.available():
        prefix = radio.read(4)

        # ---------- SENSOR DATA ----------
        if prefix == b'SENS':
            while not radio.available():
                time.sleep(0.001)

            chunk_count = int.from_bytes(radio.read(1), "big")
            print(f"📥 Receiving {chunk_count} sensor chunks...")

            received = bytearray()
            for i in range(chunk_count):
                while not radio.available():
                    time.sleep(0.001)
                chunk = radio.read(32)
                received.extend(chunk)
                print(f"📦 Sensor chunk {i+1}/{chunk_count}", end="\r")

            try:
                sensor_text = received.rstrip(b'\x00').decode()
                print("\n✅ Sensor data received:")
                print(sensor_text)

                # --- Convert to a dictionary ---
                parts = sensor_text.split("|")
                temp_parsed_data = {
                    "capture_timestamp": parts[0]
                }

                for item in parts[1:]:
                    if ':' in item:
                        key, value_raw = item.split(":", 1)
                        # Clean the key to be a valid JSON key (e.g., remove 'T', 'H', 'P')
                        clean_key = key.strip()
                        # Clean the value to be just the number
                        value = ''.join(c for c in value_raw if c.isdigit() or c == '.' or c == '-')
                        try:
                            temp_parsed_data[clean_key] = float(value)
                        except (ValueError, TypeError):
                            temp_parsed_data[clean_key] = value_raw # fallback to raw value
                
                # --- Store the parsed dictionary ---
                parsed_sensor_data = temp_parsed_data # <-- CHANGE: Store the dictionary directly
                print("👍 Sensor data parsed and ready for upload.")

            except Exception as e:
                print("❌ Failed to decode or parse sensor data:", e)

        # ---------- IMAGE DATA (No changes needed in this block) ----------
        elif prefix == b'IMAG':
            # This logic is working well, so we keep it as is.
            length_bytes = radio.read(4)
            total_len = int.from_bytes(length_bytes, "big")
            print(f"\n🖼️ Receiving image ({total_len} bytes)...")

            received = bytearray()
            while len(received) < total_len:
                if radio.available():
                    chunk = radio.read(32)
                    received.extend(chunk)
                time.sleep(0.002)

            try:
                # Use slice to be safe against extra padding bytes
                img = Image.frombytes("RGB", (64, 64), bytes(received[:total_len]))
                filename = f"received_{uuid.uuid4().hex}.jpg"
                img.save(filename)
                print(f"✅ Image saved as {filename}")

                with open(filename, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode()

                os.remove(filename)
            except Exception as e:
                print("❌ Image error:", e)

    # ---------- Upload When Both Are Ready ----------
    # <-- CHANGE: Check for the parsed dictionary now
    if parsed_sensor_data and image_base64:
        firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json"

        # <-- CHANGE: The payload is now structured with a nested JSON object
        upload_payload = {
            "upload_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sensor_readings": parsed_sensor_data, # Upload the whole dictionary
            "image_base64": image_base64
        }

        try:
            res = requests.post(firebase_url, json=upload_payload)
            if res.status_code == 200:
                print("✅ Uploaded structured data to Firebase.")
            else:
                print("❌ Upload failed. Status code:", res.status_code)
        except Exception as e:
            print("❌ Firebase error:", e)

        # <-- CHANGE: Reset the new state variable
        parsed_sensor_data = None
        image_base64 = None
        print("🔄 Ready for next data set.")
