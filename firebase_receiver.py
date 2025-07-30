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
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

print("ðŸ“¡ Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            radio.writeAckPayload(1, b'ACK')
            print("ðŸ¤ Handshake complete.")
            break

# ---------- Listen for Image ----------
while True:
    if radio.available():
        prefix = radio.read(4)
        # ---------- SENSOR DATA ----------
        if prefix == b'SENS':
            while not radio.available():
                time.sleep(0.001)

            chunk_count = int.from_bytes(radio.read(1), "big")
            print(f"Receiving {chunk_count} sensor chunks...")

            received = bytearray()
            for i in range(chunk_count):
                while not radio.available():
                    time.sleep(0.001)
                chunk = radio.read(32)
                received.extend(chunk)
                print(f"Sensor chunk {i+1}/{chunk_count}", end="\r")

            try:
                sensor_text = received.rstrip(b'\x00').decode()
                print("\nâœ… Sensor data received:")
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
                print("ðŸ‘ Sensor data parsed and ready for upload.")

            except Exception as e:
                print("âŒ Failed to decode or parse sensor data:", e)
                
        # ---------- Listen for Image ----------
                
        # ---------- IMAGE DATA ----------
        elif prefix == b'IMAG':
            print("\n??? Receiving image...")

            while not radio.available():
                time.sleep(0.001)

            # Step 1: Read total image length
            length_bytes = radio.read(4)
            total_len = int.from_bytes(length_bytes, "big")
            print(f"?? Expected image size: {total_len} bytes")

            # Step 2: Calculate how many 32-byte chunks
            chunk_count = (total_len + 31) // 32
            print(f"?? Receiving {chunk_count} image chunks...")
            
            chunks_received = 0
            received = bytearray()
            while len(received) < total_len:
                if radio.available():
                    chunk = radio.read(32)
                    received.extend(chunk)
                    chunks_received += 1
                    print(f"Received chunk {chunks_received}/{chunk_count}", end="\r")
                time.sleep(0.002)

            try:
                jpeg_data = bytes(received[:total_len])
                file_name = f"received_{uuid.uuid4().hex}.jpg"
                with open(file_name, "wb") as f:
                    f.write(jpeg_data)
                print(f"âœ… JPEG saved as {file_name}")
                
                firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json"
                data = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "sensor_readings": temp_parsed_data,
                    "image_base64": b64
                }
                res = requests.post(firebase_url, json=data)
                if res.status_code == 200:
                    print("âœ… Uploaded to Firebase.")
                else:
                    print("âŒ Firebase error:", res.status_code)

                os.remove(file_name)

            except Exception as e:
                print("âŒ JPEG receive error:", e)
                

        parsed_sensor_data = None
        image_base64 = None
        print("ðŸ”„ Ready for next data set.")
