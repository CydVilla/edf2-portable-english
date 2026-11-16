#!/bin/sh
set -eu

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 ORIGINAL.iso TEXTURE_PACK_DIRECTORY PSPDECRYPT_DIRECTORY ENGLISH.iso" >&2
    exit 2
fi

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
base_iso=$1
texture_pack=$2
pspdecrypt_dir=$3
output_iso=$4
python=${PYTHON:-python3}
c_compiler=${CC:-clang}
cpp_compiler=${CXX:-clang++}

if [ -e "$output_iso" ] || [ -L "$output_iso" ]; then
    echo "Output already exists: $output_iso" >&2
    exit 2
fi
if [ ! -f "$base_iso" ] || [ ! -d "$texture_pack/ui" ] ||
   [ ! -f "$pspdecrypt_dir/PrxDecrypter.cpp" ] || [ ! -d "$pspdecrypt_dir/libkirk" ]; then
    echo 'Check the input ISO, the extracted ULJS00374 texture folder, and the pspdecrypt source folder.' >&2
    exit 2
fi

"$python" -B - "$project_dir" "$base_iso" <<'PY'
import mmap
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from bps import check_base

try:
    import PIL
except ImportError:
    sys.exit("Install the Python dependencies from requirements.txt first.")
if PIL.__version__ != "11.3.0":
    sys.exit("Install Pillow 11.3.0 from requirements.txt first.")

try:
    with Path(sys.argv[2]).open("rb") as source:
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            check_base(data)
except (OSError, ValueError) as error:
    sys.exit(str(error))
PY

scratch=$(mktemp -d "${TMPDIR:-/tmp}/edf2p-build.XXXXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
trap 'exit 1' HUP INT TERM

for source in "$pspdecrypt_dir"/libkirk/*.c; do
    name=$(basename "$source" .c)
    "$c_compiler" -O2 -I "$pspdecrypt_dir/libkirk" -c "$source" -o "$scratch/$name.o"
done
"$c_compiler" -O2 -I "$pspdecrypt_dir/libkirk" "$project_dir/rebuild_install.c" \
    "$scratch"/*.o -o "$scratch/rebuild-install"
"$cpp_compiler" -std=c++11 -O2 -I "$pspdecrypt_dir" "$project_dir/decrypt_prx.cpp" \
    "$pspdecrypt_dir/PrxDecrypter.cpp" "$scratch"/*.o -o "$scratch/decrypt-prx"

"$python" -B "$project_dir/build.py" "$base_iso" "$texture_pack" "$scratch/english.bps" \
    --complete "$scratch/rebuild-install" --localize "$scratch/decrypt-prx" --layout-polish
"$python" -B "$project_dir/bps.py" "$base_iso" "$scratch/english.bps" "$output_iso"
