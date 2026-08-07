import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app
app.run(port=5001, use_reloader=False, debug=False)
