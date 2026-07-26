#!/usr/bin/env python3
"""Reconstruct split MEHDORA patches without changing their bytes."""

from pathlib import Path


patch_dir = Path(__file__).resolve().parents[1] / "patches"
for first_part in sorted(patch_dir.glob("*.patch.part-00")):
    output = first_part.with_name(first_part.name.removesuffix(".part-00"))
    parts = sorted(patch_dir.glob(f"{output.name}.part-*"))
    output.write_bytes(b"".join(part.read_bytes() for part in parts))
    print(f"reconstructed {output.name} from {len(parts)} parts")
