"""Write a C header holding a file's bytes:  python embed.py INPUT OUTPUT NAME"""
import sys
from pathlib import Path
data = Path(sys.argv[1]).read_bytes()
name = sys.argv[3]
rows = [', '.join(str(b) for b in data[i:i + 24]) for i in range(0, len(data), 24)]
Path(sys.argv[2]).write_text(
    f'// Generated from {Path(sys.argv[1]).name} by ofx/tools/embed.py\n'
    f'static const unsigned char {name}[] = {{\n' + ',\n'.join(rows) + '\n};\n'
    f'static const unsigned int {name}Size = {len(data)};\n')
