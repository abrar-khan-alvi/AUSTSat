from RF24 import RF24
import time
import uuid

# --- Radio Setup --- (Same as before)
radio = RF24(22, 0)
radio.begin()
radio.setChannel(76)
radio.setPALevel(2, False) # Use RF24_PA_MAX for better range
radio.setAutoAck(True)
radio.enableDynamicPayloads()
radio.enableAckPayload() # Important for our protocol
radio.openReadingPipe(1, b'1Node')
radio.startListening()

print("📡 Waiting for START...")
while True:
    if radio.available():
        # Wait for the START command
        msg = radio.read(radio.getDynamicPayloadSize())
        if msg == b'START':
            # Acknowledge the start to sync up
            radio.stopListening()
            radio.write(b'ACK_START')
            radio.startListening()
            print("🤝 Handshake complete. Waiting for metadata.")
            break
    time.sleep(0.1)

# --- Main Loop ---
while True:
    if radio.available():
        # 1. Receive the image size
        length_bytes = radio.read(4)
        total_len = int.from_bytes(length_bytes, "big")
        print(f"🔢 Expected size: {total_len} bytes. Sending ACK_META.")

        # 2. Acknowledge the metadata
        radio.stopListening()
        radio.write(b'ACK_META')
        radio.startListening()

        # 3. Receive the image data, chunk by chunk
        received_data = bytearray()
        chunk_count = (total_len + 31) // 32
        
        for i in range(chunk_count):
            # Wait for the next chunk with a timeout
            start_time = time.time()
            while not radio.available():
                if time.time() - start_time > 2.0: # 2-second timeout per chunk
                    print("❌ Timeout waiting for chunk!")
                    break # Break inner loop
                time.sleep(0.01)
            
            if not radio.available():
                break # Break outer loop if timeout occurred

            # We have a chunk, read it
            chunk = radio.read(32)
            received_data.extend(chunk)
            print(f"📥 Received chunk {i+1}/{chunk_count}")

            # Acknowledge the chunk so sender can send the next one
            ack_payload = f"ACK{i}".encode()
            radio.stopListening()
            radio.write(ack_payload)
            radio.startListening()

        # 4. Final verification and save
        if len(received_data) >= total_len:
            jpeg_data = bytes(received_data[:total_len])
            file_name = f"received_{uuid.uuid4().hex}.jpg"
            with open(file_name, "wb") as f:
                f.write(jpeg_data)
            print(f"✅ Image transfer complete! Saved as {file_name}")
        else:
            print(f"❌ Transfer failed. Received {len(received_data)}/{total_len} bytes.")
