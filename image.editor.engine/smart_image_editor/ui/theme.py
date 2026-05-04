APP_QSS = """
QMainWindow, QWidget {
    background: #20213b;
    color: #f4f0ff;
    font-family: Segoe UI, Arial;
    font-size: 13px;
}
QMenuBar {
    background: #25264a;
    color: #f4f0ff;
    padding: 6px;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #7c5cff;
    border-radius: 6px;
}
QMenu {
    background: #2a2b52;
    color: #f4f0ff;
    border: 1px solid #4f4f82;
}
QPushButton {
    background: #7c5cff;
    color: white;
    border: 0;
    border-radius: 10px;
    padding: 9px 13px;
    font-weight: 600;
}
QPushButton:hover {
    background: #9d7cff;
}
QPushButton:disabled {
    background: #494966;
    color: #aaa6c9;
}
QLabel#TitleLabel {
    color: #ffcf5c;
    font-size: 20px;
    font-weight: 800;
}
QLabel#SectionTitle {
    color: #69f0d5;
    font-size: 15px;
    font-weight: 700;
    margin-top: 12px;
}
QLabel#SubtitleLabel {
    color: #69f0d5;
    font-size: 14px;
}
QFrame#Panel {
    background: #292a50;
    border: 1px solid #414274;
    border-radius: 8px;
}
QFrame#PreviewFrame {
    background: #16172e;
    border: 1px solid #3d3f72;
    border-radius: 8px;
}
QLabel#PreviewOverlayLabel {
    background: #202241;
    color: #f4f0ff;
    border: 1px solid #55588c;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 700;
}
QFrame#ToolPageHeader {
    background: #202241;
    border: 1px solid #3d3f72;
    border-radius: 8px;
}
QLabel#ToolPageTitle {
    color: #ffffff;
    font-size: 19px;
    font-weight: 800;
}
QLabel#ToolPageDescription {
    color: #aaaed0;
    font-size: 12px;
}
QFrame#ToolSection {
    background: transparent;
    border: 0;
}
QToolButton#SectionToggle {
    background: #1d1e38;
    color: #f4f0ff;
    border: 1px solid #414274;
    border-radius: 8px;
    padding: 9px 10px;
    font-weight: 700;
    text-align: left;
}
QToolButton#SectionToggle:hover {
    background: #30325c;
    border: 1px solid #676aa0;
}
QFrame#SliderRow {
    background: #202241;
    border: 1px solid #353762;
    border-radius: 8px;
}
QFrame#SliderRow:hover {
    background: #252750;
    border: 1px solid #55588c;
}
QLabel#SliderTitle {
    color: #f4f0ff;
    font-weight: 600;
}
QLabel#SliderValue {
    color: #69f0d5;
    min-width: 34px;
    font-weight: 700;
}
QPushButton#SmallButton {
    background: #383a68;
    color: #f4f0ff;
    border: 1px solid #55588c;
    border-radius: 6px;
    padding: 5px 8px;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#MiniButton, QPushButton#RecentButton {
    background: #383a68;
    color: #f4f0ff;
    border: 1px solid #55588c;
    border-radius: 7px;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 700;
}
QPushButton#MiniButton:hover, QPushButton#RecentButton:hover {
    background: #4b4e82;
}
QScrollArea#ToolScroll {
    border: none;
    background: transparent;
}
QPushButton#SmallButton:hover {
    background: #4b4e82;
}
QTabWidget::pane {
    border: 0;
}
QTabBar::tab {
    background: #1d1e38;
    color: #aaa6c9;
    padding: 8px 10px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #383a68;
    color: #ffffff;
}
QSlider::groove:horizontal {
    height: 8px;
    background: #3d3f72;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -5px 0;
    background: #69f0d5;
    border-radius: 9px;
}
QListWidget, QTextEdit {
    background: #1d1e38;
    color: #f4f0ff;
    border: 1px solid #414274;
    border-radius: 12px;
    padding: 8px;
}
QListWidget::item {
    padding: 8px;
    border-radius: 8px;
}
QListWidget::item:selected {
    background: #ff6b9d;
    color: white;
}
QComboBox {
    background: #1d1e38;
    color: #f4f0ff;
    border: 1px solid #414274;
    border-radius: 10px;
    padding: 7px;
}
QScrollArea {
    border: none;
}
"""
