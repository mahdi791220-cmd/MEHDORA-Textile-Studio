"""Colour analysis and recolouring primitives for MEHDORA.

The engine works in CIE Lab rather than RGB.  Lab separates perceived
lightness from chroma, which lets a colourway change hue while retaining the
small light/dark variations that describe print texture, shading and edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ColorCluster:
    rgb: tuple[int, int, int]
    population: int


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert uint8 sRGB to floating-point CIE Lab (D65)."""
    srgb = np.asarray(rgb, dtype=np.float32) / 255.0
    linear = np.where(
        srgb <= 0.04045,
        srgb / 12.92,
        ((srgb + 0.055) / 1.055) ** 2.4,
    )
    xyz = linear @ np.asarray(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ],
        dtype=np.float32,
    ).T
    xyz /= np.asarray([0.95047, 1.0, 1.08883], dtype=np.float32)
    delta = 6.0 / 29.0
    f = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3.0 * delta**2) + 4.0 / 29.0,
    )
    return np.stack(
        (116.0 * f[..., 1] - 16.0, 500.0 * (f[..., 0] - f[..., 1]),
         200.0 * (f[..., 1] - f[..., 2])),
        axis=-1,
    ).astype(np.float32)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Convert floating-point CIE Lab (D65) to uint8 sRGB."""
    values = np.asarray(lab, dtype=np.float32)
    fy = (values[..., 0] + 16.0) / 116.0
    fx = fy + values[..., 1] / 500.0
    fz = fy - values[..., 2] / 200.0
    delta = 6.0 / 29.0
    f = np.stack((fx, fy, fz), axis=-1)
    xyz = np.where(
        f > delta,
        f**3,
        3.0 * delta**2 * (f - 4.0 / 29.0),
    )
    xyz *= np.asarray([0.95047, 1.0, 1.08883], dtype=np.float32)
    linear = xyz @ np.asarray(
        [
            [3.2404542, -1.5371385, -0.4985314],
            [-0.9692660, 1.8760108, 0.0415560],
            [0.0556434, -0.2040259, 1.0572252],
        ],
        dtype=np.float32,
    ).T
    linear = np.clip(linear, 0.0, 1.0)
    srgb = np.where(
        linear <= 0.0031308,
        12.92 * linear,
        1.055 * np.power(linear, 1.0 / 2.4) - 0.055,
    )
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def _rgb_colors_to_lab(colors: Sequence[Sequence[int]]) -> np.ndarray:
    return rgb_to_lab(np.asarray(colors, dtype=np.uint8))


def analyze_colors(rgba: np.ndarray, count: int) -> list[ColorCluster]:
    """Return dominant visible colours ordered by pixel population."""
    image = Image.fromarray(rgba, "RGBA")
    image.thumbnail((420, 420), Image.Resampling.LANCZOS)
    pixels = np.asarray(image, dtype=np.uint8).reshape(-1, 4)
    pixels = pixels[pixels[:, 3] > 24, :3]
    if not len(pixels):
        return []
    if len(pixels) > 32_000:
        pixels = pixels[:: max(1, len(pixels) // 32_000)]

    lab = rgb_to_lab(pixels)
    unique = np.unique(lab, axis=0)
    count = max(1, min(int(count), len(unique)))

    # Percentile seeds are stable between runs, unlike random k-means seeds.
    seed_positions = np.linspace(0, len(unique) - 1, count).astype(int)
    centers = unique[seed_positions]
    for _ in range(20):
        distances = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = distances.argmin(axis=1)
        updated = centers.copy()
        for index in range(count):
            members = lab[labels == index]
            if len(members):
                updated[index] = members.mean(axis=0)
        if np.allclose(centers, updated, atol=0.25):
            centers = updated
            break
        centers = updated

    distances = ((lab[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    labels = distances.argmin(axis=1)
    populations = np.bincount(labels, minlength=count)
    order = np.argsort(populations)[::-1]
    center_rgb = lab_to_rgb(centers[order])
    return [
        ColorCluster(tuple(int(channel) for channel in rgb), int(populations[i]))
        for rgb, i in zip(center_rgb, order)
    ]


def extract_reference_palette(
    rgba: np.ndarray, count: int
) -> list[tuple[int, int, int]]:
    """Extract a colorway reference without letting large greys hide accents."""
    candidates = analyze_colors(rgba, max(12, int(count) * 2))
    if len(candidates) <= count:
        return [cluster.rgb for cluster in candidates]

    colors = np.asarray([cluster.rgb for cluster in candidates], dtype=np.uint8)
    lab = rgb_to_lab(colors)
    chroma = np.linalg.norm(lab[:, 1:], axis=1)
    population = np.asarray([cluster.population for cluster in candidates], dtype=np.float32)
    population /= max(1.0, population.max())

    selected: list[int] = []

    def add(index: int) -> None:
        if index not in selected and len(selected) < count:
            selected.append(int(index))

    # Preserve the dark anchor, light fabric/base color, and strongest accents.
    add(int(np.argmin(lab[:, 0])))
    add(int(np.argmax(lab[:, 0])))
    accent_score = chroma * (0.65 + 0.35 * np.sqrt(population))
    for index in np.argsort(accent_score)[::-1]:
        add(int(index))

    # If slots remain, add perceptually distant candidates for useful variety.
    while len(selected) < min(count, len(candidates)):
        remaining = [i for i in range(len(candidates)) if i not in selected]
        distances = [
            min(np.linalg.norm(lab[i] - lab[j]) for j in selected)
            for i in remaining
        ]
        add(remaining[int(np.argmax(distances))])
    return [candidates[index].rgb for index in selected]


def apply_colorway(
    rgba: np.ndarray,
    sources: Sequence[Sequence[int]],
    targets: Sequence[Sequence[int]],
    *,
    texture: float = 1.0,
    chroma_detail: float = 1.0,
    edge_softness: float = 0.12,
    vibrance: float = 1.16,
    chunk_rows: int = 512,
) -> np.ndarray:
    """Map source colour families to targets while retaining design detail.

    ``texture`` controls retained light/dark relief. ``chroma_detail`` keeps
    subtle within-family colour variation. ``edge_softness`` controls a
    perceptual feather across nearby colour families to avoid posterized
    contours. ``vibrance`` restores print-friendly chroma after blending.
    """
    if not sources or len(sources) != len(targets):
        raise ValueError("sources and targets must be non-empty and equal length")
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("rgba must have shape (height, width, 4)")

    source_lab = _rgb_colors_to_lab(sources)
    target_lab = _rgb_colors_to_lab(targets)
    height, width = rgba.shape[:2]
    output = np.empty_like(rgba)
    output[:, :, 3] = rgba[:, :, 3]
    chunk_rows = max(1, int(chunk_rows))

    # Distance matrices are the largest temporary allocation. Processing in
    # strips keeps print-scale textile files from multiplying memory usage by
    # the number of detected colours.
    for top in range(0, height, chunk_rows):
        bottom = min(height, top + chunk_rows)
        original_rgb = np.ascontiguousarray(rgba[top:bottom, :, :3])
        pixel_lab = rgb_to_lab(original_rgb)
        flat = pixel_lab.reshape(-1, 3)
        distances = ((flat[:, None, :] - source_lab[None, :, :]) ** 2).sum(axis=2)
        if len(sources) > 1 and edge_softness > 0:
            sigma = 8.0 + 68.0 * float(np.clip(edge_softness, 0.0, 1.0))
            nearest_pair = np.argpartition(distances, kth=1, axis=1)[:, :2]
            pair_distances = np.take_along_axis(distances, nearest_pair, axis=1)
            pair_weights = np.exp(-pair_distances / (2.0 * sigma * sigma))
            pair_weights /= pair_weights.sum(axis=1, keepdims=True) + 1e-8
            weights = np.zeros_like(distances, dtype=np.float32)
            np.put_along_axis(weights, nearest_pair, pair_weights, axis=1)
            mapped_source = weights @ source_lab
            mapped_target = weights @ target_lab
        else:
            nearest = distances.argmin(axis=1)
            mapped_source = source_lab[nearest]
            mapped_target = target_lab[nearest].copy()

        result_lab = mapped_target
        result_lab[:, 0] += (flat[:, 0] - mapped_source[:, 0]) * float(texture)
        result_lab[:, 1:] += (
            flat[:, 1:] - mapped_source[:, 1:]
        ) * float(chroma_detail)
        result_lab[:, 1:] *= max(0.0, float(vibrance))
        result_lab[:, 0] = np.clip(result_lab[:, 0], 0.0, 100.0)
        result_lab[:, 1:] = np.clip(result_lab[:, 1:], -128.0, 127.0)
        output[top:bottom, :, :3] = lab_to_rgb(
            result_lab.reshape(pixel_lab.shape)
        )
    return output


def create_colorway_targets(
    sources: Sequence[Sequence[int]],
    palette: Iterable[Sequence[int]],
    variant: int,
    *,
    preserve_lightness: float = 0.68,
) -> list[tuple[int, int, int]]:
    """Create a deterministic, role-aware palette assignment.

    Light source families stay mapped to light palette colours and dark source
    families to dark colours. Mid-tone chromatic colours rotate between
    variants, creating diversity without random or disharmonious assignments.
    """
    source_list = [tuple(map(int, color)) for color in sources]
    palette_list = [tuple(map(int, color)) for color in palette]
    if not source_list or not palette_list:
        return []

    source_lab = _rgb_colors_to_lab(source_list)
    palette_lab = _rgb_colors_to_lab(palette_list)
    source_order = np.argsort(source_lab[:, 0])
    palette_order = list(np.argsort(palette_lab[:, 0]))

    if len(palette_order) > 2:
        middle = palette_order[1:-1]
        shift = int(variant) % len(middle)
        middle = middle[shift:] + middle[:shift]
        if (int(variant) // len(middle)) % 2:
            middle = list(reversed(middle))
        palette_order = [palette_order[0], *middle, palette_order[-1]]

    assigned = [None] * len(source_list)
    for rank, source_index in enumerate(source_order):
        if len(source_order) == 1:
            palette_rank = len(palette_order) // 2
        else:
            palette_rank = round(rank * (len(palette_order) - 1) / (len(source_order) - 1))
        assigned[source_index] = palette_list[palette_order[palette_rank]]

    # A dark reference palette should not turn a naturally airy design into a
    # uniformly dark print. Keep each source family's original lightness role
    # while still allowing some of the reference palette's contrast.
    preservation = float(np.clip(preserve_lightness, 0.0, 1.0))
    if preservation:
        assigned_lab = _rgb_colors_to_lab(assigned)
        assigned_lab[:, 0] = (
            source_lab[:, 0] * preservation
            + assigned_lab[:, 0] * (1.0 - preservation)
        )
        assigned = [
            tuple(int(channel) for channel in color)
            for color in lab_to_rgb(assigned_lab)
        ]
    return assigned
