import "../styles"

AppleButton {
    property bool modeSwitch: false
    implicitWidth: modeSwitch ? Design.dutyModeButtonWidth : Design.dutyActionButtonWidth
    implicitHeight: Design.dutyActionButtonHeight
}
