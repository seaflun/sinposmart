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
                    ToolFieldLabel { text: "所屬單位" }
                    AppleTextField {
                        objectName: "civilpowerHomeUnitField"
                        Layout.fillWidth: true
                        text: "大園救護分隊"
                        readOnly: true
                        enabled: panel.editable
                    }
                }
                RowLayout {
                    ToolFieldLabel { text: "日期" }
                    AppleTextField {
                        id: dateField
                        objectName: "civilpowerDateField"
                        Layout.fillWidth: true
                        text: panel.controller.dateText
                        placeholderText: "YYYY-MM-DD"
                        readOnly: true
                        clickAction: function() { dateCalendar.openForCurrentDate() }
                        enabled: panel.editable
                    }
                    AppleCalendarButton {
                        id: dateCalendar
                        objectName: "civilpowerDateCalendarButton"
                        dateText: dateField.text
                        dateFormat: "iso"
                        anchorItem: dateField
                        popupParent: Overlay.overlay
                        enabled: panel.editable
                        onDateSelected: function(value) { dateField.text = value }
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
                        readOnly: true
                        clickAction: function() { timePicker.openForCurrentTime() }
                        enabled: panel.editable
                    }
                    AppleButton {
                        objectName: "civilpowerTimeClockButton"
                        Layout.preferredWidth: 36
                        Layout.preferredHeight: 34
                        tone: "info"
                        Accessible.name: "選擇時間"
                        enabled: panel.editable
                        onClicked: timePicker.openForCurrentTime()
                        contentItem: Item {
                            Rectangle {
                                anchors.centerIn: parent
                                width: 17
                                height: 17
                                radius: width / 2
                                color: Design.transparent
                                border.width: Design.borderWidth
                                border.color: parent.parent.foregroundColor
                            }
                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: parent.height / 2 - 5
                                width: Design.borderWidth
                                height: 6
                                color: parent.parent.foregroundColor
                            }
                            Rectangle {
                                x: parent.width / 2
                                y: parent.height / 2
                                width: 5
                                height: Design.borderWidth
                                color: parent.parent.foregroundColor
                            }
                        }
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
                    ToolFieldLabel { text: "狀態" }
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

    Popup {
        id: timePicker
        objectName: "civilpowerTimePickerPopup"
        parent: Overlay.overlay
        x: {
            const point = timeField.mapToItem(parent, timeField.width - width, timeField.height + 6)
            return Math.max(8, Math.min(point.x, parent.width - width - 8))
        }
        y: {
            const below = timeField.mapToItem(parent, 0, timeField.height + 6)
            if (below.y + height <= parent.height - 8)
                return below.y
            return Math.max(8, timeField.mapToItem(parent, 0, -height - 6).y)
        }
        width: 228
        padding: 12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: Design.radiusMedium
            color: Design.panel
            border.width: Design.borderWidth
            border.color: Design.border
        }
        function openForCurrentTime() {
            const match = String(timeField.text || "").match(/^(\d{2}):(\d{2})$/)
            hourTumbler.currentIndex = match ? Number(match[1]) : 0
            minuteTumbler.currentIndex = match ? Number(match[2]) : 0
            open()
        }
        contentItem: ColumnLayout {
            spacing: 8
            Label {
                Layout.fillWidth: true
                text: "選擇時間"
                color: Design.infoText
                font.pixelSize: Design.bodySize
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: 8
                Tumbler {
                    id: hourTumbler
                    objectName: "civilpowerHourTumbler"
                    Layout.preferredWidth: 66
                    Layout.preferredHeight: 108
                    model: 24
                    visibleItemCount: 3
                    wrap: true
                    delegate: Label {
                        required property var modelData
                        text: String(modelData).padStart(2, "0")
                        opacity: 1.0 - Math.abs(Tumbler.displacement) / (hourTumbler.visibleItemCount / 2)
                        color: Tumbler.displacement === 0 ? Design.text : Design.muted
                        font.pixelSize: Design.bodySize
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Label {
                    text: ":"
                    color: Design.text
                    font.pixelSize: Design.bodySize
                    font.bold: true
                }
                Tumbler {
                    id: minuteTumbler
                    objectName: "civilpowerMinuteTumbler"
                    Layout.preferredWidth: 66
                    Layout.preferredHeight: 108
                    model: 60
                    visibleItemCount: 3
                    wrap: true
                    delegate: Label {
                        required property var modelData
                        text: String(modelData).padStart(2, "0")
                        opacity: 1.0 - Math.abs(Tumbler.displacement) / (minuteTumbler.visibleItemCount / 2)
                        color: Tumbler.displacement === 0 ? Design.text : Design.muted
                        font.pixelSize: Design.bodySize
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                AppleButton {
                    Layout.fillWidth: true
                    text: "取消"
                    tone: "neutralStrong"
                    onClicked: timePicker.close()
                }
                AppleButton {
                    Layout.fillWidth: true
                    text: "套用"
                    tone: "primary"
                    onClicked: {
                        timeField.text = String(hourTumbler.currentIndex).padStart(2, "0")
                                + ":" + String(minuteTumbler.currentIndex).padStart(2, "0")
                        timePicker.close()
                    }
                }
            }
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
