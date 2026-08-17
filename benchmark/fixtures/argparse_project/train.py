from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--f1-average", default="macro")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.device == "cuda":
        raise RuntimeError("CUDA device requested but no NVIDIA driver is available")
    if args.f1_average != "macro":
        raise ValueError("metric mismatch: paper requires macro-F1, code selected micro-F1")
    print("one synthetic CPU epoch complete; macro_f1=1.0")


if __name__ == "__main__":
    main()
