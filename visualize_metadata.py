import argparse
import datetime
import json
from pathlib import Path
from typing import TypedDict

import matplotlib.pyplot as plt


class YarbMetadata(TypedDict):
    timestamp: float
    filename: str
    dump_time: float
    total_keys: int
    dump_size_mb: float


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-file", default="metadata.json")
    parser.add_argument("--months", default="1")

    args = parser.parse_args()
    metadata: list[YarbMetadata] = json.loads(Path(args.metadata_file).read_text())
    dated_metadata = [(datetime.datetime.fromtimestamp(m["timestamp"]), m) for m in metadata]
    min_dt = datetime.datetime.now() - datetime.timedelta(days=int(30 * float(args.months)))
    dated_metadata = [(dt, m) for dt, m in dated_metadata if dt > min_dt]
    dts = [dt for dt, _ in dated_metadata]

    fig, axes = plt.subplots(nrows=3, sharex="all", figsize=(8, 10))
    for ax, key, title in zip(
        axes,
        ("total_keys", "dump_size_mb", "dump_time"),
        ("Total key #", "Dump size, Mb", "Dump time, sec"),
    ):
        ax.plot(dts, [m[key] for _, m in dated_metadata])  # type: ignore
        ax.set_ylabel(title)

    axes[-1].set_xlabel("Date")
    fig.tight_layout()
    fig.savefig("metadata.png")
    print("Metadata visualization saved")
