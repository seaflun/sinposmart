import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: panel
    required property var controller
    objectName: "civilpowerDialog"
    canClose: !controller.isRunning
    property bool editable: !controller.isRunning && !hostWindow.backend.readOnlyAcceptance

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "民力系統"
            canClose: panel.canClose
            closeAction: function() { panel.close() }
        }
        ToolUsageHistory {
            backend: panel.hostWindow.backend
            toolId: "civilpower"
            currentOperatorOnly: true
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 10
                ToolSectionTitle { text: "義消到勤／退勤" }
                Label {
                    Layout.fillWidth: true
                    text: "使用目前值班人員帳號登打出入紀錄。"
                    color: Design.muted
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    ToolFieldLabel { text: "日期" }
                    AppleTextField {
                        id: dateField
                        objectName: "civilpowerDateField"
                        Layout.fillWidth: true
                        text: panel.controller.dateText
                        placeholderText: "YYYY-MM-DD"
                        enabled: panel.editable
                    }
                }
                RowLayout {
                    ToolFieldLabel { text: "時間" }
                    AppleTextField {
                        id: timeField
                        objectName: "civilpowerTimeField"
                        Layout.fillWidth: true
                        text: panel.controller.timeText
                        placeholderText: "HH:MM"
                        enabled: panel.editable
                    }
                }
                RowLayout {
                    ToolFieldLabel { text: "人員" }
                    AppleComboBox {
                        id: memberCombo
                        objectName: "civilpowerMemberCombo"
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        model: panel.controller.members
                        textRole: "label"
                        valueRole: "member_id"
                        currentIndex: -1
                        onModelChanged: currentIndex = -1
                        displayText: currentIndex < 0 ? "請選擇義消" : currentText
                        enabled: panel.editable
                    }
                }
                RowLayout {
                    ToolFieldLabel { text: "出入" }
                    AppleComboBox {
                        id: actionCombo
                        objectName: "civilpowerActionCombo"
                        Layout.fillWidth: true
                        model: ["到勤", "退勤"]
                        enabled: panel.editable
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: panel.controller.rosterStatus
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                    wrapMode: Text.Wrap
                }
                AppleButton {
                    text: "重新讀取名冊"
                    enabled: panel.editable
                    onClicked: panel.controller.refreshRoster()
                }
            }
        }
        Item { Layout.fillHeight: true }
        ToolStatusBar {
            text: panel.controller.statusText
            onDetailsRequested: function(message) { panel.hostWindow.showErrorDetails("民力系統", message) }
        }
        AppleButton {
            objectName: "civilpowerSubmitButton"
            Layout.fillWidth: true
            text: panel.controller.isRunning ? "處理中…" : "確認登打"
            tone: "primary"
            enabled: panel.editable && memberCombo.currentIndex >= 0
            onClicked: panel.controller.prepareRun(dateField.text, timeField.text,
                String(memberCombo.currentValue || ""), actionCombo.currentText)
        }
    }

    AppleDialog {
        id: confirmation
        objectName: "civilpowerConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 380
        modal: true
        title: "確認民力出入登記"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始登打"
        onAccepted: panel.controller.confirmRun()
        onRejected: panel.controller.cancelPendingRun()
        Label {
            width: parent.width
            text: panel.controller.confirmationSummary
            wrapMode: Text.Wrap
            color: Design.text
        }
    }
    Connections {
        target: panel.controller
        function onConfirmationRequested() { confirmation.open() }
        function onRosterChanged() { memberCombo.currentIndex = -1 }
        function onDefaultsLoaded() {
            dateField.text = panel.controller.dateText
            timeField.text = panel.controller.timeText
            memberCombo.currentIndex = -1
            actionCombo.currentIndex = 0
        }
    }
}
