import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Frame {
    id: toolPanelHeader
    property alias text: headerTitle.text
    property var closeAction: null
    property bool canClose: true
    Layout.fillWidth: true
    implicitHeight: 36
    padding: 0
    background: Rectangle {
        color: Design.transparent
    }

    contentItem: RowLayout {
        spacing: 10

        AppleButton {
            objectName: "toolPanelBackButton"
            implicitWidth: 36
            implicitHeight: 36
            leftPadding: 0
            rightPadding: 0
            cornerRadius: implicitHeight / 2
            text: "‹"
            font.pixelSize: Design.toolBackIconSize
            tone: "neutral"
            enabled: toolPanelHeader.canClose && toolPanelHeader.closeAction !== null
            Accessible.name: "關閉側邊工具"
            onClicked: toolPanelHeader.closeAction()
        }

        ToolPanelTitle {
            id: headerTitle
        }
    }
}
