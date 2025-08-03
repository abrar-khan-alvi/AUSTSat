from RF24 import RF24
import time
from PIL import Image
import uuid
import base64
import requests
import os

# --- NEW: Configuration for Reliable Transfer ---
CHUNK_NUM_BYTES = 2   # Use 2 bytes for the chunk index
CHUNK_DATA_SIZE = 32 - CHUNK_NUM_BYTES # 30 bytes of data per packet
RECEPTION_TIMEOUT_S = 5.0 # Increased timeout for waiting between chunks

# ## NEW ##: Configuration for saving images locally for debugging
IMAGE_SAVE_DIR = "received_images"
os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)


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

# --- NEW: Reliable Receive Function ---
def receive_reliable_payload(data_type_name="Data"):
    """
    Receives a payload that was sent in reliable, indexed chunks.
    Returns the complete byte array on success, or None on failure.
    """
    # 1. Wait for the chunk count metadata packet
    print(f"Waiting for chunk count for {data_type_name}...")
    num_chunks_bytes = receive_reliable_chunk(-1, "Chunk Count")
    if not num_chunks_bytes:
        print(f"❌ Timed out waiting for chunk count. Aborting {data_type_name} reception.")
        return None
    
    num_chunks = int.from_bytes(num_chunks_bytes, 'big')
    print(f"Expecting {num_chunks} chunks for {data_type_name}.")
    
    if num_chunks == 0:
        return bytearray() # Handle zero-length data

    # 2. Receive all the data chunks
    received_chunks = {}
    last_chunk_time = time.time()
    
    while len(received_chunks) < num_chunks:
        # Receive one chunk with its index
        chunk_tuple = receive_reliable_chunk(len(received_chunks), "Data") # Expecting next chunk
        
        if chunk_tuple:
            chunk_index, chunk_data = chunk_tuple
            
            # If it's a new chunk, store it
            if chunk_index not in received_chunks:
                received_chunks[chunk_index] = chunk_data
                print(f"Received {data_type_name} chunk {chunk_index+1}/{num_chunks}", end="\r")
            
            # Always reset the timeout when any valid packet is received
            last_chunk_time = time.time()
        
        # Check for overall timeout
        if time.time() - last_chunk_time > RECEPTION_TIMEOUT_S:
            print(f"\n⚠️ Timed out waiting for next chunk after {RECEPTION_TIMEOUT_S}s.")
            return None

    print(f"\n✅ All {num_chunks} chunks for {data_type_name} received.")
    
    # 3. Reassemble the payload from sorted chunks
    full_payload = bytearray()
    for i in range(num_chunks):
        full_payload.extend(received_chunks[i])
        
    return full_payload

def receive_reliable_chunk(expected_index, log_prefix):
    """
    Waits for a single chunk, sends an ACK, and returns the (index, data).
    An expected_index of -1 is for metadata packets.
    """
    if radio.available():
        payload = radio.read(32)
        
        # Parse the chunk index from the start of the payload
        received_index = int.from_bytes(payload[:CHUNK_NUM_BYTES], 'big')
        
        # Prepare the ACK: b'ACK' + index (2 bytes)
        ack_payload = b'ACK' + received_index.to_bytes(2, 'big')
        
        # Load the ACK payload to be sent back automatically by the radio
        radio.writeAckPayload(1, ack_payload)
        
        # For metadata (like total chunk count), which has a special index
        if received_index == 65535 and expected_index == -1:
            print(f"  ✅ ACK sent for {log_prefix}")
            return payload[CHUNK_NUM_BYTES:CHUNK_NUM_BYTES+4] # Return the 4-byte count

        # For regular data chunks
        elif received_index < 65535 and expected_index != -1:
            # This is a data chunk. Return its index and data.
            chunk_data = payload[CHUNK_NUM_BYTES:]
            if received_index < expected_index:
                # This is a duplicate of a past chunk, our ACK was likely lost.
                # The ACK has already been sent, so we just ignore the data.
                pass # print(f"  (Got duplicate for #{received_index}, re-ACKed)")
            return received_index, chunk_data
    
    return None # No chunk available

# ---------- Handshake (Same as before) ----------
print("📡 Waiting for SYNC...")
while True:
    if radio.available():
        msg = radio.read(4)
        if msg == b'SYNC':
            # Send ACK for the SYNC
            radio.writeAckPayload(1, b'ACK')
            print("🤝 Handshake complete.")
            break
    time.sleep(0.01)

# ---------- Main Listening Loop ----------
while True:
    print("\n---------------------------------")
    print("Ready for next data prefix...")
    
    # Wait for a prefix 'SENS' or 'IMAG'
    prefix_bytes = receive_reliable_chunk(-1, "Prefix")
    
    if not prefix_bytes:
        # print("...(listening)...")
        time.sleep(0.1)
        continue

    prefix = prefix_bytes.rstrip(b'\x00')

    # ---------- SENSOR DATA ----------
    if prefix == b'SENS':
        print("\n--- Receiving Sensor Data ---")
        sensor_bytes = receive_reliable_payload("Sensor Data")
        
        if sensor_bytes is not None:
            try:
                sensor_text = sensor_bytes.rstrip(b'\x00').decode()
                print("\n✅ Sensor data received and reassembled:")
                print(sensor_text)

                parts = sensor_text.split("|")
                parsed_data = {"capture_timestamp": parts[0]}
                for item in parts[1:]:
                    if ':' in item:
                        key, value_raw = item.split(":", 1)
                        value = ''.join(c for c in value_raw if c.isdigit() or c == '.' or c == '-')
                        try:
                            parsed_data[key.strip()] = float(value)
                        except (ValueError, TypeError):
                            parsed_data[key.strip()] = value_raw
                
                latest_sensor_data = parsed_data
                print("👍 Sensor data parsed and stored for the next upload.")

            except Exception as e:
                print(f"❌ Failed to decode or parse sensor data: {e}")
        else:
            print("❌ Sensor data reception failed.")
            
    # ---------- IMAGE DATA ----------
    elif prefix == b'IMAG':
        print("\n--- Receiving Image Data ---")
        image_bytes = receive_reliable_payload("Image Data")
        
        if image_bytes is not None:
            total_len = len(image_bytes)
            print(f"📊 Reception finished. Received {total_len} bytes.")

            try:
                timestamp_str = time.strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp_str}_complete_{total_len}.jpg"
                filepath = os.path.join(IMAGE_SAVE_DIR, filename)
                with open(filepath, 'wb') as f:
                    f.write(image_bytes)
                print(f"💾 Raw image data saved to: {filepath}")
            except Exception as e:
                print(f"❌ Error saving raw image file: {e}")

            try:
                image_base64 = base64.b64encode(image_bytes).decode('utf-8')

                if latest_sensor_data is None:
                    print("⚠️ No sensor data was received before this image. Uploading with placeholder.")
                    latest_sensor_data = {"error": "data not received"}

                data_payload = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "sensor_readings": latest_sensor_data,
                    "image_base64": image_base64
                }

                print("⬆️  Uploading combined data to Firebase...")
                res = requests.post(firebase_url, json=data_payload)
                print("Firebase Response:", res.status_code, res.text)
                
                # Reset sensor data so it isn't accidentally re-used
                latest_sensor_data = None

            except Exception as e:
                print(f"A critical error occurred during processing or Firebase upload: {e}")
        else:
            print("❌ Image data reception failed.")
