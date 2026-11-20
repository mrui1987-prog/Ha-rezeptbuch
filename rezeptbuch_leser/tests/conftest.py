import os
import sys

# Tests laufen im Ordner des Add-ons (wie im GitHub-Testlauf); app als Paket importierbar
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
