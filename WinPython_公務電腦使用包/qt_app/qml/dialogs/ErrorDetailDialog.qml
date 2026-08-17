import QtQuick
import QtQuick.Controls
import "../components"
import "../styles"

AppleDialog {
    id: errorDetailDialog
    property string detailTitle: "錯誤明細"
    property string detailText: ""

    objectName: "errorDetailDialog"
    title: errorDetailDialog.detailTitle
    standardButtons: Dialog.Close

    function openDetails(title, message) {
        const normalized = String(message || "").trim()
        if (normalized.length === 0)
            return
        errorDetailDialog.detailTitle = String(title || "錯誤明細")
        errorDetailDialog.detailText = normalized
        errorDetailDialog.open()
    }

    ScrollView {
        anchors.fill: parent
        clip: true

        AppleTextArea {
            objectName: "errorDetailTextArea"
            text: errorDetailDialog.detailText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.Wrap
            color: Design.text
            font.pixelSize: Design.labelSize
            background: Rectangle {
                radius: Design.radiusMedium
                color: Design.background
                border.color: Design.border
            }
        }
    }
}
