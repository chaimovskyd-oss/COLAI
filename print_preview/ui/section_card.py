from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy

class SectionCard(QFrame):
    def __init__(self, title: str, subtitle: str | None = None):
        super().__init__()
        self.setObjectName("SectionCard")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 14, 14, 14)
        self.layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("PanelTitle")
        self.layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PanelSubtle")
            subtitle_label.setWordWrap(True)
            self.layout.addWidget(subtitle_label)
