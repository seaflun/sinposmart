import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../styles"

Dialog {
    id: appleDialog
    modal: true
    padding: 14
    property string acceptText: "確定"
    property string rejectText: "取消"
    property string closeText: "關閉"
    property string acceptTone: "primary"
    font.pixelSize: Design.bodySize

    background: Rectangle {
        radius: Design.radiusMedium
        color: Design.panel
        border.width: Design.borderWidth
        border.color: Design.border
    }

    header: Rectangle {
        implicitHeight: 46
        radius: Design.radiusMedium
        color: Design.comboHover
        border.width: Design.borderWidth
        border.color: Design.comboBorder

        Label {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            text: appleDialog.title
            color: Design.infoText
            font.pixelSize: Design.sectionTitleSize
            font.bold: true
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
    }

    footer: Rectangle {
        implicitHeight: 52
        color: Design.subtleSurface
        border.width: Design.borderWidth
        border.color: Design.divider

        RowLayout {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            AppleButton {
                objectName: "appleDialogNoButton"
                visible: (appleDialog.standardButtons & Dialog.No) !== 0
                implicitWidth: 76
                implicitHeight: 34
                text: appleDialog.rejectText
                tone: "neutralStrong"
                onClicked: appleDialog.reject()
            }
            AppleButton {
                objectName: "appleDialogYesButton"
                visible: (appleDialog.standardButtons & Dialog.Yes) !== 0
                implicitWidth: Math.max(92, implicitContentWidth + 32)
                implicitHeight: 34
                text: appleDialog.acceptText
                tone: appleDialog.acceptTone
                onClicked: appleDialog.accept()
            }
            AppleButton {
                objectName: "appleDialogCloseButton"
                visible: (appleDialog.standardButtons & Dialog.Close) !== 0
                implicitWidth: 84
                implicitHeight: 34
                text: appleDialog.closeText
                tone: "neutralStrong"
                onClicked: appleDialog.close()
            }
        }
    }
}
