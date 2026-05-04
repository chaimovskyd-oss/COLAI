class ScaleService:
    def compute_scale(self, design_w, design_h, printable_w, printable_h, mode, custom_scale):
        if design_w <= 0 or design_h <= 0:
            return 1.0
        if mode == "100":
            return 1.0
        if mode == "fit_page":
            return min(printable_w / design_w, printable_h / design_h)
        if mode == "fit_printable":
            return min(printable_w / design_w, printable_h / design_h)
        if mode == "custom":
            return custom_scale
        return 1.0
