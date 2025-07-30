from RF24 import RF24
import time
import uuid
import base64
import requests
import os

# --- Radio Setup ---
# Standard configuration for nRF24L01+
radio = RF24(22, 0) # CE, CSN pins
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # For best range, use RF24_PA_MAX
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

# --- Global Variables ---
# This variable will store sensor data until the corresponding image arrives
latest_sensor_data = None
firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json"

# --- Phase 1: Handshake ---
# Wait for the sender to initiate contact
print("📡 Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            # Got the sync packet, send acknowledgement back
            radio.stopListening()
            radio.write(b'ACK_SYNC')
            radio.startListening()
            print("🤝 Handshake complete. Ready for data.")
            break # Exit the handshake loop and move to the main listener
    time.sleep(0.1)

# --- Phase 2: Main Listening Loop ---
# Continuously listen for different types of data transmissions
while True:
    if radio.available():
        # Read the incoming packet using its dynamic size
        payload = radio.read(radio.getDynamicPayloadSize())
        prefix = payload[:4]

        # --- SENSOR DATA HANDLING ---
        if prefix == b'SENS':
            chunk_count = int.from_bytes(payload[4:5], "big")
            print(f"\n✉️ Incoming Sensor Data: {chunk_count} chunks expected...")
            
            # Acknowledge that we received the metadata
            radio.stopListening()
            radio.write(b'ACK_SENS_META')
            radio.startListening()

            received = bytearray()
            for i in range(chunk_count):
                # Wait for the next chunk with a 2-second timeout
                start_time = time.time()
                while not radio.available():
                    if time.time() - start_time > 2.0:
                        print(f"\n❌ Timeout waiting for sensor chunk {i+1}. Aborting this receive.")
                        break # Break from the inner 'while' loop
                    time.sleep(0.01)
                
                if not radio.available():
                    break # Break from the outer 'for' loop if a timeout occurred

                # If we have data, read it and acknowledge it
                chunk = radio.read(32)
                received.extend(chunk)
                
                radio.stopListening()
                radio.write(f"S_ACK{i}".encode())
                radio.startListening()
                print(f"  📥 Received sensor chunk {i+1}/{chunk_count}", end='\r')
            
            else: # This 'else' block runs ONLY if the 'for' loop completed without a 'break'
                try:
                    sensor_text = received.rstrip(b'\x00').decode()
                    print("\n✅ Sensor data fully received. Parsing...")
                    
                    # Parse the text into a dictionary
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
                    
                    # Store the parsed data in our persistent global variable
                    latest_sensor_data = parsed_data
                    print("👍 Sensor data parsed and stored for the next upload.")

                except Exception as e:
                    print("\n❌ Failed to decode or parse sensor data:", e)

        # ---------- IMAGE DATA HANDLING ----------
        elif prefix == b'IMAG':
            total_len = int.from_bytes(payload[4:8], "big")
            chunk_count = (total_len + 31) // 32
            print(f"\n🖼️ Incoming Image: {total_len} bytes ({chunk_count} chunks) expected...")
            
            # Acknowledge metadata
            radio.stopListening()
            radio.write(b'ACK_IMAG_META')
            radio.startListening()

            received = bytearray()
            for i in range(chunk_count):
                # Wait for chunk with timeout
                start_time = time.time()
                while not radio.available():
                    if time.time() - start_time > 2.0:
                        print(f"\n❌ Timeout waiting for image chunk {i+1}. Aborting this receive.")
                        break
                    time.sleep(0.01)
                
                if not radio.available():
                    break # Exit loop

                # Read chunk and send specific ACK
                chunk = radio.read(32)
                received.extend(chunk)

                radio.stopListening()
                radio.write(f"I_ACK{i}".encode())
                radio.startListening()
                print(f"  📥 Received image chunk {i+1}/{chunk_count}", end='\r')
            
            else: # Runs ONLY if the image was fully received without a timeout
                print("\n✅ Image data fully received. Processing for upload...")
                try:
                    # Final processing and upload to Firebase
                    jpeg_data = bytes(received[:total_len])
                    image_base64 = base64.b64encode(jpeg_data).decode('utf-8')

                    if latest_sensor_data is None:
                        print("⚠️ Warning: No sensor data available. Uploading image only.")
                        latest_sensor_data = {"error": "data not received"}

                    data_payload = {
                        "upload_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "sensor_readings": latest_sensor_data,
                        "image_base64": image_base64
                    }

                    print("⬆️ Uploading combined data to Firebase...")
                    res = requests.post(firebase_url, json=data_payload)

                    if res.status_code == 200:
                        print("✅✅✅ Uploaded to Firebase successfully!")
                    else:
                        print(f"❌ Firebase error: {res.status_code}, Response: {res.text}")
                    
                    # Reset sensor data to prevent re-use
                    latest_sensor_data = None
                except Exception as e:
                    print("\n❌ A critical error occurred during JPEG processing or Firebase upload:", e)

        print("\n🔄 Ready for next transmission.")