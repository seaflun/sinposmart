import QtQuick
import QtQuick.Controls
import "../styles"

TextField {
    id: appleTextField
    property bool compact: false
    property var clickAction: null
    implicitHeight: compact ? Design.toolCompactControlHeight : 34
    leftPadding: 10
    rightPadding: 10
    font.pixelSize: Design.bodySize
    color: enabled ? Design.text : Design.muted
    placeholderTextColor: Design.muted
    selectByMouse: true

    HoverHandler {
        enabled: appleTextField.enabled && appleTextField.clickAction === null
        cursorShape: Qt.IBeamCursor
    }

    background: Rectangle {
        radius: Design.radius
        color: parent.enabled ? Design.panel : Design.softAction
        border.width: parent.activeFocus ? Design.focusBorderWidth : Design.borderWidth
        border.color: parent.activeFocus ? Design.blue : Design.border
    }

    MouseArea {
        anchors.fill: parent
        enabled: appleTextField.clickAction !== null
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        propagateComposedEvents: true
        onClicked: function(mouse) {
            appleTextField.clickAction()
            mouse.accepted = false
        }
    }
}
