"""Compare measured-energy layers for two exposures or two halves and their sum."""

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
    plot_rows([("Reference exposure", reference), ("Independent exposure", independent)], output)


def plot_rows(named_planes, output):
    grid = named_planes[0][1]["grid"]
    if any(grid != plane["grid"] for _, plane in named_planes):
        raise ValueError("The acquisitions need a common projection grid")
    labels = sorted((key for key in named_planes[0][1]["layers"] if key.endswith("_keV")),
                    key=lambda key: float(key.removesuffix("_keV")))
    rows = [[plane["layers"][label] for label in labels] for _, plane in named_planes]
    norm = Normalize(0, max(np.max(layer["mass"]) for row in rows for layer in row))
    extent = grid["extent_mm"]
    figure, axes = plt.subplots(len(rows), len(labels), squeeze=False,
                                figsize=(10.5, 3.15*len(rows) + .8), layout="constrained")
    figure.suptitle(f"GeGI  |  Measured two-strip Compton backprojections\n"
                    f"Assumed plane z = {grid['assumed_z_mm']:g} mm", fontsize=16)
    for row, ((name, _), layers) in enumerate(zip(named_planes, rows)):
        for col, (label, layer) in enumerate(zip(labels, layers)):
            axis = axes[row, col]
            image = axis.imshow(layer["mass"], origin="lower", extent=(-extent, extent, -extent, extent),
                                interpolation="nearest", cmap="magma", norm=norm)
            center = label.removesuffix("_keV")
            axis.set_title(f"{center} keV\n{layer['triggers_with_geometry']} of {layer['triggers']} triggers projected",
                           fontsize=10)
            if col == 0:
                axis.set_ylabel(f"{name}\nDetector Y (mm)")
            if row == len(rows)-1:
                axis.set_xlabel("Detector X (mm)")
            axis.tick_params(labelsize=8)
    figure.colorbar(image, ax=axes, shrink=.76, pad=.025,
                    label=f"Projected trigger weight per {grid['step_mm']:g} × {grid['step_mm']:g} mm cell")
    figure.savefig(output, dpi=180, facecolor="white")
    plt.close(figure)


def plot_exposure_study(study, output):
    rows = []
    for key, title in (("first_half", "First"), ("second_half", "Second"), ("full", "Pooled")):
        view = study["views"][key]
        selection = view["selection"]
        clock_s = selection["clock_live_time_ns"] / 1e9
        live_ms = selection["qualified_adc_live_time_ns"] / 1e6
        label = f"{title} {clock_s:.2f} s  |  {live_ms:.1f} ms qualified"
        rows.append((label, {"grid": study["grid"], "layers": view["layers"]}))
    plot_rows(rows, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exposure-study", type=Path, help="Plot the two half-second exposures and their combined result")
    parser.add_argument("planes", type=Path, nargs="*", help="Reference and independent plane files")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.exposure_study and not args.planes:
        plot_exposure_study(read_plane(args.exposure_study), args.output)
    elif not args.exposure_study and len(args.planes) == 2:
        plot(*map(read_plane, args.planes), args.output)
    else:
        parser.error("Supply two plane files or one --exposure-study")
