import time
import uuid
import base64
import requests
import os
from RF24 import RF24

# --- Radio Setup ---
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

# --- Global variables ---
latest_sensor_data = None
firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json" # YOUR FIREBASE URL

# ---------- 1. Handshake ----------
print("Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            radio.stopListening()
            radio.write(b'ACK')
            radio.startListening()
            print("Handshake complete.")
            break
    time.sleep(0.1)

# ---------- 2. Main Listening Loop ----------
print("\nReady for data...")
while True:
    if radio.available():
        prefix = radio.read(4)

        # ---------- SENSOR DATA ----------
        if prefix == b'SENS':
            print("\n--- Receiving Sensor Data ---")
            while not radio.available(): time.sleep(0.001)
            chunk_count = int.from_bytes(radio.read(1), "big")
            received = bytearray()
            for i in range(chunk_count):
                while not radio.available(): time.sleep(0.001)
                chunk = radio.read(32)
                received.extend(chunk)
            
            try:
                sensor_text = received.rstrip(b'\x00').decode()
                print("Sensor data received:", sensor_text)
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
                latest_sensor_data = parsed_data
                print("Sensor data parsed and stored.")
            except Exception as e:
                print("Failed to decode or parse sensor data:", e)
        
        # ---------- RELIABLE IMAGE RECEIVER ----------
        elif prefix == b'IMAG':
            print("\n--- Receiving Image ---")
            radio.stopListening()
            radio.write(b'ACK_IMAG')
            radio.startListening()

            # Wait for size packet
            start_time = time.time()
            while not radio.available():
                if time.time() - start_time > 2.0:
                    print("Timed out waiting for image size.")
                    break
                time.sleep(0.01)
            
            if not radio.available(): continue

            # We have the size, read it and ACK
            length_bytes = radio.read(4)
            total_len = int.from_bytes(length_bytes, "big")
            print(f"Expected image size: {total_len} bytes")
            radio.stopListening()
            radio.write(b'ACK_SIZE')
            radio.startListening()
            
            # Prepare to receive chunks
            received_data = bytearray()
            chunk_count = (total_len + 31) // 32
            
            for i in range(chunk_count):
                start_time = time.time()
                while not radio.available():
                    if time.time() - start_time > 2.0:
                        print(f"\nTimed out waiting for chunk {i+1}/{chunk_count}")
                        break
                    time.sleep(0.01)
                
                if not radio.available(): break

                chunk = radio.read(32)
                received_data.extend(chunk)
                print(f"Received chunk {i+1}/{chunk_count}", end="\r")

                ack_payload = f"ACK{i}".encode()
                radio.stopListening()
                radio.write(ack_payload)
                radio.startListening()
            
            # Wait for DONE signal
            print("\nWaiting for DONE signal...")
            start_time = time.time()
            done_received = False
            while time.time() - start_time < 2.0:
                if radio.available():
                    if radio.read(4) == b'DONE':
                        radio.stopListening()
                        radio.write(b'ACK_DONE')
                        radio.startListening()
                        print("Transfer complete signal received.")
                        done_received = True
                        break

            if done_received and len(received_data) >= total_len:
                print("Image data fully received. Processing...")
                jpeg_data = bytes(received_data[:total_len])
                image_base64 = base64.b64encode(jpeg_data).decode('utf-8')
                
                if latest_sensor_data is None:
                    print("Warning: No sensor data. Uploading with placeholder.")
                    latest_sensor_data = {"error": "data not received"}

                data_payload = {
                    "upload_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "sensor_readings": latest_sensor_data,
                    "image_base64": image_base64
                }

                print("Uploading combined data to Firebase...")
                try:
                    res = requests.post(firebase_url, json=data_payload, timeout=10)
                    if res.status_code == 200:
                        print("✅✅✅ Uploaded to Firebase successfully! ✅✅✅")
                    else:
                        print(f"Firebase error: {res.status_code}, Response: {res.text}")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to upload to Firebase: {e}")
                
                latest_sensor_data = None
            else:
                print("Transfer failed or did not complete correctly.")
        
        print("\nReady for next data set...")
