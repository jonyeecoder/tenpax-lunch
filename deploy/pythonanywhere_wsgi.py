# Paste this into the WSGI configuration file linked from PythonAnywhere's Web tab,
# replacing everything in it. Change YOUR_USERNAME to your PythonAnywhere username.
import sys

path = "/home/YOUR_USERNAME/tenpax-lunch"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa: E402,F401
