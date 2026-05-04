from dataclasses import dataclass

@dataclass
class PrintMetrics:
    paper_width_mm: float = 210.0
    paper_height_mm: float = 297.0
    printable_width_mm: float = 190.0
    printable_height_mm: float = 277.0
    margin_top_mm: float = 10.0
    margin_bottom_mm: float = 10.0
    margin_left_mm: float = 10.0
    margin_right_mm: float = 10.0
    scale: float = 1.0
    output_width_mm: float = 190.0
    output_height_mm: float = 277.0
