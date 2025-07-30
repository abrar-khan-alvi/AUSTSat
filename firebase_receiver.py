from RF24 import RF24
import time
import uuid
import base64
import requests

# --- Radio Setup --- (Same)
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

latest_sensor_data = None
firebase_url = "https://fire-authentic-f5c81-default-rtdb.firebaseio.com/image_log.json"

# ---------- 1. Handshake ----------
print("📡 Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            radio.stopListening()
            radio.write(b'ACK_SYNC') # Acknowledge the handshake
            radio.startListening()
            print("🤝 Handshake complete.")
            break

# ---------- Main Loop ----------
while True:
    if radio.available():
        # Read header and metadata
        header_payload = radio.read(5) # e.g., b'SENS' + 1 byte len, or b'IMAG' + 4 bytes len
        prefix = header_payload[:4]

        # ---------- SENSOR DATA ----------
        if prefix == b'SENS':
            chunk_count = int.from_bytes(header_payload[4:5], "big")
            print(f"\n✉️ Receiving {chunk_count} sensor chunks...")
            radio.stopListening()
            radio.write(b'ACK_SENS_META') # Acknowledge metadata
            radio.startListening()

            received = bytearray()
            for i in range(chunk_count):
                # Wait for chunk with timeout
                start_time = time.time()
                while not radio.available():
                    if time.time() - start_time > 2.0:
                        print(f"\n❌ Timeout waiting for sensor chunk {i}.")
                        break
                    time.sleep(0.01)
                if not radio.available(): break # Exit loop if timeout occurred
                
                chunk = radio.read(32)
                received.extend(chunk)
                
                # Acknowledge this specific chunk
                radio.stopListening()
                radio.write(f"S_ACK{i}".encode())
                radio.startListening()
                print(f"  📥 Received sensor chunk {i+1}/{chunk_count}", end='\r')
            else:
                # Parse and store sensor data
                # (This part is the same as your working code)
                latest_sensor_data = # ... your parsing logic here ...
                print("\n✅ Sensor data received and parsed.")
            
        # ---------- IMAGE DATA ----------
        elif prefix == b'IMAG':
            total_len = int.from_bytes(header_payload[1:5], "big")
            chunk_count = (total_len + 31) // 32
            print(f"\n🖼️ Receiving image, {chunk_count} chunks...")
            radio.stopListening()
            radio.write(b'ACK_IMAG_META') # Acknowledge metadata
            radio.startListening()

            received = bytearray()
            for i in range(chunk_count):
                # Wait for chunk with timeout
                start_time = time.time()
                while not radio.available():
                    if time.time() - start_time > 2.0:
                        print(f"\n❌ Timeout waiting for image chunk {i}.")
                        break
                    time.sleep(0.01)
                if not radio.available(): break # Exit loop

                chunk = radio.read(32)
                received.extend(chunk)

                # Acknowledge this specific chunk
                radio.stopListening()
                radio.write(f"I_ACK{i}".encode())
                radio.startListening()
                print(f"  📥 Received image chunk {i+1}/{chunk_count}", end='\r')
            else:
                # Process and upload to Firebase
                print("\n✅ Image received. Processing for upload...")
                # (This part is the same as your working code)
                # ... convert to base64 ...
                # ... build data_payload with latest_sensor_data ...
                # ... requests.post(firebase_url, json=data_payload) ...
                print("✅✅✅ Uploaded to Firebase successfully!")
                latest_sensor_data = None # Reset for next run

        print("\n🔄 Ready for next transmission.")