APP_STYLESHEET = '''
QMainWindow, QWidget {
    background: #1C1D21;
    color: #EEE6D8;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 13px;
}
QFrame#TopBar, QFrame#BottomBar {
    background: #202228;
    border-bottom: 1px solid #2E3138;
}
QFrame#BottomBar {
    border-top: 1px solid #2E3138;
    border-bottom: none;
}
QFrame#SidePanel {
    background: #1F2126;
    border: 1px solid #2D3139;
    border-radius: 14px;
}
QFrame#SectionCard {
    background: #252830;
    border: 1px solid #323641;
    border-radius: 12px;
}
QLabel#PanelTitle {
    font-size: 15px;
    font-weight: 700;
    color: #F7F1E7;
}
QLabel#PanelSubtle {
    color: #BFB7A8;
    font-size: 12px;
}
QLabel#MetricValue {
    color: #F7F1E7;
    font-weight: 600;
}
QPushButton {
    background: #2B2E36;
    color: #EEE6D8;
    border: 1px solid #3A3F49;
    border-radius: 10px;
    padding: 8px 12px;
    min-height: 20px;
}
QPushButton:hover {
    background: #343946;
}
QToolButton {
    background: #2B2E36;
    color: #EEE6D8;
    border: 1px solid #3A3F49;
    border-radius: 10px;
    padding: 8px 12px;
    min-height: 20px;
}
QToolButton:hover {
    background: #343946;
}
QPushButton#PrimaryButton {
    background: #3B82F6;
    border: 1px solid #3B82F6;
    color: white;
    font-weight: 700;
}
QPushButton#PrimaryButton:hover {
    background: #2563EB;
}
QPushButton#SuccessButton {
    background: #22C55E;
    border: 1px solid #22C55E;
    color: white;
    font-weight: 700;
}
QPushButton#WarnButton {
    background: #F59E0B;
    border: 1px solid #F59E0B;
    color: #241800;
    font-weight: 700;
}
QComboBox, QDoubleSpinBox, QSpinBox {
    background: #262A32;
    color: #F7F1E7;
    border: 1px solid #3A3F49;
    border-radius: 9px;
    padding: 6px 10px;
    min-height: 22px;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QFrame#Separator {
    color: #3A3F49;
    background: #3A3F49;
    max-height: 1px;
    margin: 4px 0;
}
QLabel#CanvasTitle {
    color: #F7F1E7;
    font-size: 20px;
    font-weight: 700;
}
QLabel#CanvasSubtle {
    color: #BFB7A8;
    font-size: 12px;
}
QLabel#WarningBanner {
    background: #4C3412;
    color: #FDE7B7;
    border: 1px solid #8A5A16;
    border-radius: 10px;
    padding: 8px 10px;
}
'''
