"""Compare the measured-energy layers of two saved GeGI plane reconstructions."""

import argparse
import gzip
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np


def read_plane(path):
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return json.load(source)


def plot(reference, independent, output):
    planes = [reference, independent]
    grid = reference["grid"]
    if grid != independent["grid"]:
        raise ValueError("The acquisitions need a common projection grid")
    labels = [key for key in reference["layers"] if key.endswith("_keV")]
    rows = [[plane["layers"][label] for label in labels] for plane in planes]
    norm = Normalize(0, max(np.max(layer["mass"]) for row in rows for layer in row))
    extent = grid["extent_mm"]
    figure, axes = plt.subplots(2, len(labels), squeeze=False, figsize=(10.5, 7.1), layout="constrained")
    figure.suptitle(f"GeGI  |  Measured two-strip Compton backprojections\n"
                    f"Assumed plane z = {grid['assumed_z_mm']:g} mm", fontsize=16)
    for row, (name, layers) in enumerate(zip(("Reference exposure", "Independent exposure"), rows)):
        for col, (label, layer) in enumerate(zip(labels, layers)):
            axis = axes[row, col]
            image = axis.imshow(layer["mass"], origin="lower", extent=(-extent, extent, -extent, extent),
                                interpolation="nearest", cmap="magma", norm=norm)
            center = label.removesuffix("_keV")
            axis.set_title(f"{center} keV\n{layer['triggers_with_geometry']} of {layer['triggers']} triggers projected",
                           fontsize=10)
            if col == 0:
                axis.set_ylabel(f"{name}\nDetector Y (mm)")
            if row == 1:
                axis.set_xlabel("Detector X (mm)")
            axis.tick_params(labelsize=8)
    figure.colorbar(image, ax=axes, shrink=.76, pad=.025,
                    label=f"Projected trigger weight per {grid['step_mm']:g} × {grid['step_mm']:g} mm cell")
    figure.savefig(output, dpi=180, facecolor="white")
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("independent", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plot(read_plane(args.reference), read_plane(args.independent), args.output)
