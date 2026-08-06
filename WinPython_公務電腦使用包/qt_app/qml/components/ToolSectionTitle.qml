import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

RowLayout {
    id: toolSectionTitle
    property alias text: titleLabel.text
    property alias font: titleLabel.font
    property color markerColor: Design.blue
    property color titleColor: Design.infoText
    Layout.fillWidth: true
    implicitHeight: Design.toolSectionMarkerHeight
    spacing: 7

    Rectangle {
        Layout.preferredWidth: Design.toolSectionMarkerWidth
        Layout.preferredHeight: Design.toolSectionMarkerHeight
        radius: width / 2
        color: toolSectionTitle.markerColor
    }

    Label {
        id: titleLabel
        color: toolSectionTitle.titleColor
        font.pixelSize: Design.controlSize
        font.bold: true
    }

    Item { Layout.fillWidth: true }
}
