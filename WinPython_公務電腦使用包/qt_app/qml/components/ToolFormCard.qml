import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Frame {
    Layout.fillWidth: true
    padding: 12
    background: Rectangle {
        radius: Design.radius
        color: Design.panel
        border.width: Design.borderWidth
        border.color: Design.border
    }
}
