import QtQuick
import QtQuick.Controls
import "../styles"

TabButton {
    id: appleTab
    implicitHeight: 40
    font.pixelSize: Design.labelSize
    font.weight: checked ? Font.DemiBold : Font.Normal
    hoverEnabled: true
    scale: down ? 0.98 : 1

    Behavior on scale {
        NumberAnimation {
            duration: appleTab.down ? 0 : Design.buttonFeedbackDuration
            easing.type: Easing.OutCubic
        }
    }

    contentItem: Text {
        text: appleTab.text
        color: appleTab.checked ? Design.text : Design.muted
        font: appleTab.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: Design.radiusTab
        color: appleTab.checked ? Design.panel
               : appleTab.down || appleTab.hovered ? Design.softActionHover
               : Design.transparent
        border.width: appleTab.activeFocus ? Design.focusBorderWidth
                      : appleTab.checked ? Design.borderWidth
                      : Design.noBorderWidth
        border.color: appleTab.activeFocus ? Design.blue : Design.border

        Behavior on color {
            ColorAnimation { duration: Design.buttonColorTransitionDuration }
        }
        Behavior on border.color {
            ColorAnimation { duration: Design.buttonColorTransitionDuration }
        }
    }
}
