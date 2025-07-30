from RF24 import RF24
import time
from PIL import Image
import uuid
import base64
import requests
import os

radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # For better range, consider RF24_PA_MAX
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

# FIX 1: Create a variable outside the loop to store the sensor data.
# This makes it persistent, so it's not forgotten between receiving sensor and image data.
latest_sensor_data = None

print("📡 Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            radio.writeAckPayload(1, b'ACK')
            print("🤝 Handshake complete.")
            break

# ---------- Main Listening Loop ----------
while True:
    if radio.available():
        prefix = radio.read(4)

        # ---------- SENSOR DATA ----------
        if prefix == b'SENS':
            while not radio.available(): time.sleep(0.001)
            chunk_count = int.from_bytes(radio.read(1), "big")
            print(f"Receiving {chunk_count} sensor chunks...")
            received = bytearray()
            for i in range(chunk_count):
                while not radio.available(): time.sleep(0.001)
                chunk = radio.read(32)
                received.extend(chunk)
            
            try:
                sensor_text = received.rstrip(b'\x00').decode()
                print("\n✅ Sensor data received:")
                print(sensor_text)

                # --- Convert to a dictionary ---
                parts = sensor_text.split("|")
                parsed_data = {"capture_timestamp": parts[0]}
                for item in parts[1:]:
                    if ':' in item:
                        key, value_raw = item.split(":", 1)
                        clean_key = key.strip()
                        value = ''.join(c for c in value_raw if c.isdigit() or c == '.' or c == '-')
                        try:
                            parsed_data[clean_key] = float(value)
                        except (ValueError, TypeError):
                            parsed_data[clean_key] = value_raw
                
                # FIX 1 (continued): Store the parsed data in our persistent variable
                latest_sensor_data = parsed_data
                print("👍 Sensor data parsed and stored for the next upload.")

            except Exception as e:
                print("❌ Failed to decode or parse sensor data:", e)
                
        # ---------- IMAGE DATA ----------
        elif prefix == b'IMAG':
            print("\n🖼️ Receiving image...")
            while not radio.available(): time.sleep(0.001)
            length_bytes = radio.read(4)
            total_len = int.from_bytes(length_bytes, "big")
            print(f"🔢 Expected image size: {total_len} bytes")
            chunk_count = (total_len + 31) // 32
            
            received = bytearray()
            while len(received) < total_len:
                if radio.available():
                    chunk = radio.read(32)
                    received.extend(chunk)
                time.sleep(0.002)

            try:
                jpeg_data = bytes(received[:total_len])
                print("✅ Image data fully received.")
                
                # FIX 2: Convert the received image data to a Base64 string for Firebase
                image_base64 = base64.b64encode(jpeg_data).decode('utf-8')

                # Now, prepare the complete payload for Firebase
                firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json"
                
                # FIX 1 (conclusion): Check if we have sensor data, then use it for the upload
                if latest_sensor_data is None:
                    print("⚠️ Warning: No sensor data was received before this image. Uploading with placeholder.")
                    latest_sensor_data = {"error": "data not received"}

                data_payload = {
                    "upload_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "sensor_readings": latest_sensor_data,
                    "image_base64": image_base64
                }

                print("⬆️ Uploading combined data to Firebase...")
                res = requests.post(firebase_url, json=data_payload)

                if res.status_code == 200:
                    print("✅✅✅ Uploaded to Firebase successfully! ✅✅✅")
                else:
                    # Added res.text for better error debugging from Firebase
                    print(f"❌ Firebase error: {res.status_code}, Response: {res.text}")
                
                # Reset the sensor data so we don't accidentally re-use old data
                latest_sensor_data = None

            except Exception as e:
                print("❌ A critical error occurred during JPEG processing or Firebase upload:", e)
        
        print("\n🔄 Ready for next data set.")