import unittest

import numpy as np

from standalone.color_engine import (
    analyze_colors,
    apply_colorway,
    create_colorway_targets,
    extract_reference_palette,
    rgb_to_lab,
)


class ColorEngineTests(unittest.TestCase):
    def test_recolor_preserves_alpha_and_lightness_detail(self):
        x = np.linspace(55, 205, 180, dtype=np.uint8)
        rgb = np.zeros((40, 180, 3), dtype=np.uint8)
        rgb[:, :, 0] = x
        rgb[:, :, 1] = x // 2
        rgb[:, :, 2] = 35
        alpha = np.tile(np.linspace(0, 255, 180, dtype=np.uint8), (40, 1))
        rgba = np.dstack((rgb, alpha))

        result = apply_colorway(rgba, [(130, 65, 35)], [(20, 105, 155)])
        self.assertTrue(np.array_equal(result[:, :, 3], alpha))

        before_l = rgb_to_lab(rgb)[:, :, 0].ravel()
        after_l = rgb_to_lab(result[:, :, :3])[:, :, 0].ravel()
        correlation = np.corrcoef(before_l, after_l)[0, 1]
        self.assertGreater(correlation, 0.97)
        self.assertGreater(np.ptp(after_l), np.ptp(before_l) * 0.72)

    def test_analysis_orders_clusters_by_population(self):
        rgba = np.zeros((100, 100, 4), dtype=np.uint8)
        rgba[:, :, 3] = 255
        rgba[:, :75, :3] = (190, 35, 45)
        rgba[:, 75:, :3] = (25, 75, 170)
        clusters = analyze_colors(rgba, 2)
        self.assertEqual(len(clusters), 2)
        self.assertGreater(clusters[0].population, clusters[1].population)
        self.assertGreater(clusters[0].rgb[0], clusters[0].rgb[2])

    def test_target_generation_retains_lightness_roles_and_varies(self):
        sources = [(20, 20, 20), (110, 60, 70), (235, 235, 225)]
        palette = [(12, 45, 80), (205, 70, 75), (230, 175, 65), (246, 239, 220)]
        first = create_colorway_targets(sources, palette, 0)
        second = create_colorway_targets(sources, palette, 1)
        first_l = rgb_to_lab(np.asarray(first, dtype=np.uint8))[:, 0]
        self.assertLess(first_l[0], first_l[2])
        self.assertNotEqual(first, second)

    def test_reference_palette_keeps_small_saturated_accents(self):
        rgba = np.zeros((100, 100, 4), dtype=np.uint8)
        rgba[:, :, :3] = (145, 145, 150)
        rgba[:, :, 3] = 255
        rgba[:12, :, :3] = (8, 25, 145)
        rgba[12:20, :, :3] = (215, 170, 65)
        palette = extract_reference_palette(rgba, 4)
        lab = rgb_to_lab(np.asarray(palette, dtype=np.uint8))
        chroma = np.linalg.norm(lab[:, 1:], axis=1)
        self.assertGreater(np.count_nonzero(chroma > 35), 1)

    def test_dark_palette_preserves_source_lightness_roles(self):
        sources = [(235, 225, 210), (170, 155, 145), (55, 45, 50)]
        dark_palette = [(5, 12, 45), (15, 30, 80), (35, 50, 105)]
        targets = create_colorway_targets(sources, dark_palette, 0)
        source_l = rgb_to_lab(np.asarray(sources, dtype=np.uint8))[:, 0]
        target_l = rgb_to_lab(np.asarray(targets, dtype=np.uint8))[:, 0]
        self.assertGreater(target_l[0], 65)
        self.assertGreater(np.corrcoef(source_l, target_l)[0, 1], 0.98)


if __name__ == "__main__":
    unittest.main()
