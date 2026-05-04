from __future__ import annotations


class InkEstimationService:
    """Estimate page ink coverage from the rendered preview bitmap."""

    @staticmethod
    def estimate(image) -> tuple[float, str]:
        if image is None:
            return 0.0, "Low"

        rgb = image.convert("RGB")
        width, height = rgb.size
        if width <= 0 or height <= 0:
            return 0.0, "Low"

        total = width * height
        coverage_sum = 0.0
        pixels = rgb.load()
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                pixel_coverage = 1.0 - ((r + g + b) / (255.0 * 3.0))
                coverage_sum += max(0.0, min(1.0, pixel_coverage))

        coverage_pct = (coverage_sum / total) * 100.0
        if coverage_pct >= 40.0:
            level = "High"
        elif coverage_pct >= 15.0:
            level = "Medium"
        else:
            level = "Low"
        return coverage_pct, level
