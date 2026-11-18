"""Start the local server (API plus the built frontend). Binds to 127.0.0.1 by default.

    python run_server.py                          # http://127.0.0.1:8000, data in backend/data
    python run_server.py --port 8010
    python run_server.py --data-dir D:\\demo-data   # keep the database and uploads elsewhere

Environment variables DRW_HOST, DRW_PORT and DRW_DATA_DIR work too.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Document Review Workbench server")
    parser.add_argument("--host", default=os.environ.get("DRW_HOST", "127.0.0.1"),
                        help="Interface to bind (default 127.0.0.1, local only)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("DRW_PORT", "8000")))
    parser.add_argument("--data-dir", default=None, help="Folder for the SQLite database and stored uploads")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["DRW_DATA_DIR"] = args.data_dir
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"WARNING: binding to {args.host} exposes the app beyond this computer. There is no login.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("app.main:create_app", factory=True, host=args.host, port=args.port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
