"""
3i Portal — Remote Log Receiver

Runs on the on-premises Windows server to receive application logs
from the Portal backend running on EC2 via Tailscale.

Receives pickled LogRecords from Python's SocketHandler and writes
them to c:\logging\portal-backend-aws\YYYY-MM-DD.log

Usage:
    python log_receiver.py

Listens on port 9020 (all interfaces). The EC2 backend connects
to this server via Tailscale at 10.90.98.123:9020.
"""

import logging
import logging.handlers
import os
import pickle
import socketserver
import struct
from datetime import date


LOG_DIR = r"c:\logging\portal-backend-aws"
LISTEN_PORT = 9020


class LogRecordStreamHandler(socketserver.StreamRequestHandler):
    """Handle incoming pickled LogRecords from a SocketHandler."""

    def handle(self):
        """Read and process LogRecords until the connection is closed."""
        while True:
            try:
                # SocketHandler sends: 4 bytes (length) + pickled data
                chunk = self.connection.recv(4)
                if len(chunk) < 4:
                    break
                data_len = struct.unpack('>L', chunk)[0]
                data = bytearray()
                while len(data) < data_len:
                    chunk = self.connection.recv(data_len - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                if len(data) < data_len:
                    break

                # Unpickle the LogRecord
                record = logging.makeLogRecord(pickle.loads(data))

                # Write to the daily log file
                logger = logging.getLogger(record.name)
                logger.handle(record)

            except Exception:
                break


class LogRecordSocketReceiver(socketserver.ThreadingTCPServer):
    """TCP server that receives log records."""
    allow_reuse_address = True
    daemon_threads = True


def main():
    os.makedirs(LOG_DIR, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Daily log file
    log_file = os.path.join(LOG_DIR, f"{date.today().isoformat()}.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Console output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    print(f"3i Portal Log Receiver")
    print(f"  Listening on port {LISTEN_PORT}")
    print(f"  Writing to {LOG_DIR}")
    print(f"  Current log file: {log_file}")
    print(f"  Press Ctrl+C to stop")
    print()

    server = LogRecordSocketReceiver(('0.0.0.0', LISTEN_PORT), LogRecordStreamHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLog receiver stopped.")
        server.shutdown()


if __name__ == '__main__':
    main()
