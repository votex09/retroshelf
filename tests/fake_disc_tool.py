"""Stands in for chdman / dolphin-tool in tests: writes a small "compressed" file and talks like the real ones.
FAKE_TOOL_FAIL=1 makes it fail; FAKE_TOOL_SLOW=seconds makes it take that long (for stopping it)."""
import os, sys, time

args = sys.argv[1:]
cmd, rest = args[0], args[1:]
opts = {rest[i]: rest[i + 1] for i in range(0, len(rest) - 1) if rest[i].startswith("-")}
if os.environ.get("FAKE_TOOL_FAIL"):
    print("Error: input file is not valid", flush=True)
    sys.exit(1)
if cmd in ("createcd", "createdvd", "convert"):
    with open(opts["-i"], "rb") as f:
        data = f.read()
    slow = float(os.environ.get("FAKE_TOOL_SLOW") or 0)
    for pct in (0, 50, 100):
        sys.stdout.write(f"\rCompressing, {pct}.0% complete... (ratio=40.0%)")
        sys.stdout.flush()
        time.sleep(slow / 3)
    with open(opts["-o"], "wb") as f:
        f.write((b"MComprHD" if cmd != "convert" else b"RVZ\x01") + cmd.encode() + b"\0" + data[:64])
    print("\nCompression complete ... final ratio = 40.0%")
elif cmd == "verify":
    sys.stdout.write("\rVerifying, 50.0% complete...")
    print("\nOverall SHA1 verification successful!")
else:
    print("Invalid command")
    sys.exit(1)
