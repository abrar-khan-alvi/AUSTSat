# --- Receiver Code (Updated and More Robust) ---
from RF24 import RF24
from PIL import Image
import time
import base64
import requests
import uuid
import os

# --- Radio setup (same as before) ---
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openReadingPipe(1, b'1Node')
radio.startListening()

# It's a good idea to print the radio details to be sure it's working
radio.printDetails()

sensor_data = None
image_base64 = None

# ---------- Handshake (This part is working, no changes needed) ----------
print("📡 Waiting for handshake...")
handshake_complete = False
while not handshake_complete:
    if radio.available():
        msg = radio.read(radio.getDynamicPayloadSize())
        if msg == b'SYNC':
            radio.writeAckPayload(1, b'ACK')
            print("🤝 Handshake complete.")
            handshake_complete = True
    time.sleep(0.01)

# ---------- Receive Loop ----------
while True:
    if radio.available():
        prefix = radio.read(4)

        # ---------- SENSOR DATA (Adding timeout for robustness) ----------
        if prefix == b'SENS':
            print("\n📥 Receiving sensor data...")
            
            # Wait for the chunk count packet with a timeout
            start_time = time.time()
            while not radio.available():
                if time.time() - start_time > 2.0: # 2 second timeout
                    print("\n❌ Timed out waiting for sensor chunk count!")
                    break
            if not radio.available(): continue # If timed out, skip to next loop iteration

            chunk_count = int.from_bytes(radio.read(1), "big")
            print(f"Expecting {chunk_count} sensor chunks...")

            # ... (rest of your sensor code is okay, but could also benefit from timeouts) ...
            received = bytearray()
            for i in range(chunk_count):
                start_time = time.time()
                while not radio.available():
                     if time.time() - start_time > 2.0:
                         print(f"\n❌ Timed out waiting for sensor chunk {i+1}!")
                         break
                if not radio.available(): break # Break from this for-loop
                
                chunk = radio.read(32)
                received.extend(chunk)
                print(f"Received sensor chunk {i+1}/{chunk_count}", end="\r")

            try:
                sensor_text = received.rstrip(b'\x00').decode()
                print("\n✅ Sensor data received:")
                print(sensor_text)
                sensor_data = sensor_text
            except Exception as e:
                print("\n❌ Failed to decode sensor data:", e)


        # ---------- IMAGE DATA (THIS IS THE CRITICAL FIX) ----------
        elif prefix == b'IMAG':
            # FIX: WAIT FOR THE IMAGE LENGTH PACKET TO ARRIVE
            start_time = time.time()
            while not radio.available():
                if time.time() - start_time > 2.0: # 2 second timeout
                    print("\n❌ Timed out waiting for image length packet!")
                    break
            # If we timed out, continue to the next main loop iteration
            if not radio.available():
                continue

            length_bytes = radio.read(4)
            total_len = int.from_bytes(length_bytes, "big")
            
            # Sanity check the length. If it's crazy, something is wrong.
            if total_len != 12288: # 64 * 64 * 3
                print(f"\n❌ Received corrupt image length: {total_len}. Expected 12288. Aborting image reception.")
                continue

            print(f"\n🖼️ Receiving image ({total_len} bytes)...")

            received = bytearray()
            last_reception_time = time.time()
            
            # FIX: This loop now has a timeout
            while len(received) < total_len:
                if radio.available():
                    chunk = radio.read(32)
                    received.extend(chunk)
                    last_reception_time = time.time() # Reset timeout
                
                # If we haven't received a chunk in over 2 seconds, give up
                if time.time() - last_reception_time > 2.0:
                    print(f"\n❌ Timed out receiving image data. Got {len(received)}/{total_len} bytes.")
                    break
            
            # Only proceed if we received all the data
            if len(received) >= total_len:
                try:
                    # Slice the buffer to the exact expected size to avoid errors from extra bytes
                    img_bytes = bytes(received[:total_len])
                    img = Image.frombytes("RGB", (64, 64), img_bytes)
                    filename = f"received_{uuid.uuid4().hex}.jpg"
                    img.save(filename)
                    print(f"\n✅ Image saved as {filename}")

                    with open(filename, "rb") as f:
                        image_base64 = base64.b64encode(f.read()).decode()

                    os.remove(filename)
                except Exception as e:
                    print("\n❌ Image processing error:", e)

    # ---------- Upload Logic (no changes needed) ----------
    if sensor_data and image_base64:
        # ... your upload code ...
        print("✅ Data uploaded. Resetting for next transmission.")
        sensor_data = None
        image_base64 = None
