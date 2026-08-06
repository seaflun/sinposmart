import QtQuick
import QtQuick.Controls
import "../styles"

TextArea {
    leftPadding: 10
    rightPadding: 10
    topPadding: 8
    bottomPadding: 8
    font.pixelSize: Design.bodySize
    selectByMouse: true
    wrapMode: TextEdit.Wrap

    background: Rectangle {
        radius: Design.radius
        color: Design.panel
        border.width: parent.activeFocus ? Design.focusBorderWidth : Design.borderWidth
        border.color: parent.activeFocus ? Design.blue : Design.border
    }
}
