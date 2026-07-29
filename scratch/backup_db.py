import os
import shutil

instance_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance")
sqlite_path = os.path.join(instance_dir, "app.sqlite")
backup_path = os.path.join(instance_dir, "app.sqlite.backup")

if os.path.exists(sqlite_path):
    shutil.copy2(sqlite_path, backup_path)
    print(f"[OK] Backup created successfully at {backup_path}")
else:
    print("[INFO] No local SQLite database found at instance/app.sqlite yet.")
