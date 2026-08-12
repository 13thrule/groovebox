"""Plays the audio stream coming from the R4 groovebox sketch through
this PC's speakers. The board writes one raw 16-bit unsigned little-
endian PCM sample (32768 = silence) per 2 bytes at a fixed 16000 Hz
over USB serial; this reads that stream and feeds it to the default
audio output in real time.

Run: python groovebox_player.py [COM_PORT]
If no port is given, it tries to auto-detect an Arduino-like device.
"""

import sys
import time
import threading
import queue

import serial
import serial.tools.list_ports
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BAUD = 921600
BUFFER_CHUNKS = 64  # ~64 * blocksize samples of slack before over/underrun


def find_port():
    for p in serial.tools.list_ports.comports():
        if "Arduino" in (p.description or "") or "USB Serial" in (p.description or ""):
            return p.device
    ports = list(serial.tools.list_ports.comports())
    if len(ports) == 1:
        return ports[0].device
    return None


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_port()
    if not port:
        print("Couldn't auto-detect the board's serial port.")
        print("Available ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  {p.device} -- {p.description}")
        print("\nRun again with the port explicitly: python groovebox_player.py COM9")
        return

    print(f"Opening {port} at {BAUD} baud...")
    ser_holder = {"ser": serial.Serial(port, BAUD, timeout=1)}

    sample_queue = queue.Queue(maxsize=BUFFER_CHUNKS * 4)
    running = True

    def reconnect():
        # Unplugging the board (e.g. to wire something) kills the
        # Windows COM handle even after it's plugged back in on the
        # same port -- have to close and reopen, not just keep reading.
        while running:
            try:
                try:
                    ser_holder["ser"].close()
                except Exception:
                    pass
                time.sleep(1.0)
                ser_holder["ser"] = serial.Serial(port, BAUD, timeout=1)
                print(f"[reconnected to {port}]")
                return
            except serial.SerialException:
                time.sleep(1.0)  # board still unplugged -- keep retrying

    def reader():
        while running:
            try:
                data = ser_holder["ser"].read(256)
            except serial.SerialException:
                print(f"[lost connection to {port}, reconnecting...]")
                reconnect()
                continue
            if data:
                try:
                    sample_queue.put_nowait(data)
                except queue.Full:
                    pass  # drop if the audio callback can't keep up -- avoids unbounded latency growth

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    raw_leftover = b""  # 0 or 1 leftover byte, when a read splits a sample across two chunks
    float_leftover = np.array([], dtype=np.float32)

    def audio_callback(outdata, frames, time_info, status):
        nonlocal raw_leftover, float_leftover
        if status:
            print(status)

        needed = frames
        chunks = [float_leftover]
        have = len(float_leftover)
        float_leftover = np.array([], dtype=np.float32)

        while have < needed:
            try:
                raw = sample_queue.get_nowait()
            except queue.Empty:
                break
            combined_raw = raw_leftover + raw
            raw_leftover = b""
            if len(combined_raw) % 2 == 1:
                raw_leftover = combined_raw[-1:]
                combined_raw = combined_raw[:-1]
            if not combined_raw:
                continue
            samples = np.frombuffer(combined_raw, dtype="<u2")  # little-endian uint16
            floats = (samples.astype(np.float32) - 32768.0) / 32768.0
            chunks.append(floats)
            have += len(floats)

        combined = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        if len(combined) >= needed:
            outdata[:, 0] = combined[:needed]
            float_leftover = combined[needed:]
        else:
            outdata[: len(combined), 0] = combined
            outdata[len(combined) :, 0] = 0.0  # underrun -- fill with silence rather than stale/garbage data

    print(f"Playing at {SAMPLE_RATE} Hz. Ctrl+C to stop.")
    try:
        with sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
            blocksize=256,
        ):
            while True:
                sd.sleep(1000)
    except KeyboardInterrupt:
        pass
    finally:
        running = False
        ser_holder["ser"].close()
        print("\nStopped.")


if __name__ == "__main__":
    main()
