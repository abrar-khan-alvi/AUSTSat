from RF24 import RF24
from PIL import Image
import time
import camera
from sense import read_environmental_data
import os

# --- Setup ---
radio = RF24(22, 0) # Assumes CE=22, CSN=0 (GPIO25 if using SPI0,0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # Use RF24_PA_HIGH
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.openWritingPipe(b'1Node')
radio.stopListening()

# =============================================================================
# FIXED: ROBUST HANDSHAKE
# =============================================================================
print("Attempting handshake...")
# Send SYNC and wait for the custom ACK payload.
# The write() will block until it gets a standard ACK. 
# The isAckPayloadAvailable() checks if it also came with our custom payload.
radio.write(b'SYNC') 
if radio.isAckPayloadAvailable():
    response = radio.read(radio.getDynamicPayloadSize())
    if response == b'ACK':
        print("✅ Handshake complete. Starting transfer.")
    else:
        print("❌ Handshake failed. Received wrong ACK. Exiting.")
        exit()
else:
    print("❌ Handshake failed. No ACK received. Exiting.")
    exit()

# =============================================================================
# CONSISTENT SEND FUNCTION
# =============================================================================
def send_data(prefix, data_bytes):
    """Sends data with a prefix and chunk-based protocol."""
    global radio
    chunk_size = 32
    
    # Pad the data to be a multiple of chunk_size
    padding_needed = (chunk_size - (len(data_bytes) % chunk_size)) % chunk_size
    data_bytes += b'\x00' * padding_needed
    
    chunks = [data_bytes[i:i+chunk_size] for i in range(0, len(data_bytes), chunk_size)]
    chunk_count = len(chunks)

    print(f"Sending prefix '{prefix.decode()}' with {chunk_count} chunks...")

    # 1. Send prefix
    radio.write(prefix)
    
    # 2. Send chunk count (as 1 byte)
    radio.write(chunk_count.to_bytes(1, 'big'))
    
    # 3. Send all the chunks
    for i, chunk in enumerate(chunks):
        radio.write(chunk)
    print(f"✅ Sent {prefix.decode()} data.")
    time.sleep(0.05) # Small delay between SENS and IMAG blocks

# ---------- Send Sensor Data ----------
timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
env = read_environmental_data()
sensor_text = f"{timestamp}|T:{env['temperature']:.2f}C|H:{env['humidity']:.2f}%|P:{env['pressure']:.2f}hPa"
send_data(b'SENS', sensor_text.encode())

# ---------- Send Image ----------
filename = camera.capture_photo()
img = Image.open(filename).convert("RGB").resize((64, 64))
img_bytes = img.tobytes()
os.remove(filename) # Clean up photo
send_data(b'IMAG', img_bytes)

print("\n🚀 All data sent.")
