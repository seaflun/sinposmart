import QtQuick
import QtQuick.Controls
import "../styles"

CheckBox {
    id: appleCheck
    spacing: 7
    font.pixelSize: Design.bodySize

    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: appleCheck.leftPadding
        y: (appleCheck.height - height) / 2
        radius: Design.radiusSmall
        color: appleCheck.checked ? Design.blue : Design.panel
        border.width: Design.borderWidth
        border.color: appleCheck.checked ? Design.blue : Design.border

        Text {
            anchors.centerIn: parent
            visible: appleCheck.checked
            text: "✓"
            color: Design.panel
            font.pixelSize: Design.captionSize
            font.bold: true
        }
    }
    contentItem: Text {
        leftPadding: appleCheck.indicator.width + appleCheck.spacing
        text: appleCheck.text
        color: appleCheck.enabled ? Design.text : Design.muted
        font: appleCheck.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
