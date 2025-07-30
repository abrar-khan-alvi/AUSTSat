from RF24 import RF24
from PIL import Image
import time
import camera # Assuming this is your camera library
import uuid
import os

# --- Radio Setup --- (Same as before)
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # Use RF24_PA_MAX for better range
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

# --- Function to reliably send a packet and wait for a specific ACK ---
def send_and_wait_for_ack(payload, ack_payload, retries=5, timeout=0.2):
    for _ in range(retries):
        radio.write(payload)
        
        radio.startListening()
        start_time = time.time()
        while time.time() - start_time < timeout:
            if radio.available():
                response = radio.read(radio.getDynamicPayloadSize())
                if response == ack_payload:
                    radio.stopListening()
                    return True
        radio.stopListening()
        print(f"Timed out waiting for {ack_payload.decode()}, retrying...")
    return False

# ---------- 1. Handshake ----------
print("📡 Attempting handshake...")
if not send_and_wait_for_ack(b'START', b'ACK_START'):
    print("❌ Handshake failed. Exiting.")
    exit()
print("🤝 Handshake complete.")

# ---------- 2. Capture & Compress Image ----------
filename = camera.capture_photo()
img = Image.open(filename).convert("RGB").resize((64, 64))
jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
img.save(jpeg_filename, format="JPEG", quality=50)
with open(jpeg_filename, "rb") as f:
    jpeg_bytes = f.read()
os.remove(jpeg_filename)
print(f"📦 JPEG size: {len(jpeg_bytes)} bytes")

# ---------- 3. Send Metadata ----------
print("✉️ Sending image size...")
if not send_and_wait_for_ack(len(jpeg_bytes).to_bytes(4, 'big'), b'ACK_META'):
    print("❌ Failed to send metadata. Exiting.")
    exit()
print("✅ Receiver acknowledged metadata.")

# ---------- 4. Send Image in Confirmed Chunks ----------
chunk_size = 32
chunks = [jpeg_bytes[i:i+chunk_size] for i in range(0, len(jpeg_bytes), chunk_size)]

for i, chunk in enumerate(chunks):
    if len(chunk) < chunk_size: # Pad the last chunk
        chunk += b'\x00' * (chunk_size - len(chunk))
    
    ack_needed = f"ACK{i}".encode()
    print(f"📤 Sending chunk {i+1}/{len(chunks)}...")
    if not send_and_wait_for_ack(chunk, ack_needed, retries=8):
        print(f"❌ FAILED to send chunk {i+1}. Aborting transfer.")
        break
else: # This 'else' belongs to the 'for' loop, it runs only if the loop completed without a 'break'
    print("✅✅✅ All chunks sent and acknowledged! Transfer successful.")
