from RF24 import RF24
from PIL import Image
import time
import camera
from sense import read_environmental_data, read_motion_data
import uuid
import os

# --- NEW: Configuration for Reliable Transfer ---
RETRY_TIMEOUT = 0.05  # 50ms timeout for waiting for an ACK
MAX_RETRIES = 5       # Max number of retries for a single chunk before giving up
CHUNK_NUM_BYTES = 2   # Use 2 bytes for the chunk index
CHUNK_DATA_SIZE = 32 - CHUNK_NUM_BYTES # 30 bytes of data per packet

radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False)
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

# --- NEW: Reliable Send Function ---
def send_reliable_payload(payload_bytes, data_type_name="Data"):
    """
    Splits a byte payload into chunks and sends them reliably with an ACK/retry mechanism.
    Returns True on success, False on failure.
    """
    # 1. Chunk the data
    chunks = [payload_bytes[i:i + CHUNK_DATA_SIZE] for i in range(0, len(payload_bytes), CHUNK_DATA_SIZE)]
    num_chunks = len(chunks)
    print(f"Preparing to send {num_chunks} chunks for {data_type_name}...")

    # 2. Send the number of chunks first (reliably)
    # The receiver needs to know how many chunks to expect.
    # We use a special chunk index -1 for this metadata.
    if not send_reliable_chunk(num_chunks.to_bytes(4, 'big'), -1, "Chunk Count"):
        print(f"❌ Failed to send chunk count for {data_type_name}. Aborting.")
        return False
    
    # 3. Send each data chunk with its index
    for i, chunk_data in enumerate(chunks):
        if not send_reliable_chunk(chunk_data, i, f"{data_type_name} Chunk"):
            print(f"❌ Failed to send chunk {i}/{num_chunks}. Aborting transfer.")
            return False # Abort if any chunk fails after all retries
    
    return True

def send_reliable_chunk(chunk_data, chunk_index, log_prefix):
    """
    Sends a single chunk and waits for a specific ACK. Retries on timeout.
    A chunk_index of -1 is used for metadata before the main transfer.
    """
    # Pad the chunk if it's smaller than the data size
    if len(chunk_data) < CHUNK_DATA_SIZE:
        chunk_data += b'\x00' * (CHUNK_DATA_SIZE - len(chunk_data))

    # For metadata (like total chunk count), we send it with a special index
    if chunk_index == -1:
        # Special packet for metadata. We'll use a 4-byte payload.
        payload = b'\xFF\xFF' + chunk_data[:4] # Use index 65535 as a magic number for metadata
    else:
        # Standard data packet: [index (2 bytes)] + [data (30 bytes)]
        payload = chunk_index.to_bytes(CHUNK_NUM_BYTES, 'big') + chunk_data

    for attempt in range(MAX_RETRIES):
        radio.stopListening()
        # print(f"  > Sending {log_prefix} #{chunk_index}, Attempt {attempt+1}")
        radio.write(payload)

        # Immediately switch to listening for the ACK
        radio.startListening()
        
        start_time = time.time()
        while time.time() - start_time < RETRY_TIMEOUT:
            if radio.available():
                ack_payload = radio.read(radio.getDynamicPayloadSize())
                
                # Check if it's a valid ACK for our chunk
                if len(ack_payload) >= 5 and ack_payload[:3] == b'ACK':
                    ack_index = int.from_bytes(ack_payload[3:], 'big')
                    
                    expected_index = 65535 if chunk_index == -1 else chunk_index
                    if ack_index == expected_index:
                        print(f"  ✅ ACK received for {log_prefix} #{chunk_index}")
                        return True # Success!
                
            time.sleep(0.001) # Small delay to prevent busy-waiting

        # If loop finishes, it's a timeout
        print(f"  ⚠️ Timeout waiting for ACK on {log_prefix} #{chunk_index}. Retrying...")
        
    # If all retries fail
    return False


# ---------- Handshake (Same as before) ----------
radio.write(b'SYNC')
print("📡 Sent SYNC, waiting for ACK...")
radio.startListening()
start = time.time()
ack_ok = False
while time.time() - start < 3:
    if radio.available():
        response = radio.read(radio.getDynamicPayloadSize())
        if response == b'ACK':
            print("🤝 Handshake ACK received, starting data transfer.")
            ack_ok = True
            break
if not ack_ok:
    print("❌ Handshake failed. Exiting.")
    exit()
radio.stopListening()


# ---------- 1. Read and Send Sensor Data ----------
print("\n--- Sending Sensor Data ---")
timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
env = read_environmental_data()
motion = read_motion_data()
sensor_text = (
    f"{timestamp}|T:{env['temperature']}C|H:{env['humidity']}%|P:{env['pressure']}hPa|"
    f"Pitch:{motion['orientation']['pitch']}|Roll:{motion['orientation']['roll']}|Yaw:{motion['orientation']['yaw']}"
)
sensor_bytes = sensor_text.encode()

# Send 'SENS' prefix (reliably)
if not send_reliable_chunk(b'SENS', -1, "Prefix"):
    print("❌ Failed to send SENS prefix. Aborting.")
    exit()

# Send the actual sensor data payload
if send_reliable_payload(sensor_bytes, "Sensor Data"):
    print("✅ Sensor data sent successfully.")
else:
    print("❌ Failed to send sensor data. Aborting.")
    exit()

# Small delay between data types
time.sleep(1) 

# ---------- 2. Capture & Send Image Data ----------
print("\n--- Sending Image Data ---")
filename = camera.capture_photo("image.jpg")
img = Image.open(filename).convert("RGB").resize((1024, 1024))
jpeg_filename = f"/tmp/compressed_{uuid.uuid4().hex}.jpg"
img.save(jpeg_filename, format="JPEG", quality=50)

with open(jpeg_filename, "rb") as f:
    jpeg_bytes = f.read()
os.remove(jpeg_filename)
print(f"📦 JPEG size: {len(jpeg_bytes)} bytes")

# Send 'IMAG' prefix (reliably)
if not send_reliable_chunk(b'IMAG', -1, "Prefix"):
    print("❌ Failed to send IMAG prefix. Aborting.")
    exit()

# Send the actual image data payload
if send_reliable_payload(jpeg_bytes, "Image Data"):
    print("✅ Compressed image sent successfully.")
else:
    print("❌ Failed to send image data.")

print("\nAll tasks complete.")
