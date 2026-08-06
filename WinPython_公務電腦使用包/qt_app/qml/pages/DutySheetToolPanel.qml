import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: dutySheetDialog
    required property var controller
    required property var errorHandler
    property alias workbookPath: dutyWorkbookField.text
    signal browseWorkbookRequested
    objectName: "dutySheetDialog"
    canClose: !dutySheetDialog.controller.isRunning

    QtObject {
        id: window
        readonly property var backend: dutySheetDialog.controller
        readonly property color ink: dutySheetDialog.hostWindow.ink
        readonly property color muted: dutySheetDialog.hostWindow.muted
        readonly property real width: dutySheetDialog.hostWindow.width

        function shiftSlashDate(value, days) {
            return dutySheetDialog.hostWindow.shiftSlashDate(value, days);
        }
    }

    AppleDialog {
        id: dutyVehicleAddDialog
        parent: dutySheetDialog.hostWindow.contentItem
        objectName: "dutyVehicleAddDialog"
        anchors.centerIn: parent
        width: Math.min(window.width - 72, 440)
        modal: true
        title: "新增車輛"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "新增車輛"
        onOpened: {
            dutyVehicleCodeField.text = "";
            dutyVehiclePlateField.text = "";
        }
        onAccepted: dutySheetDialog.controller.addVehicleOption(dutyVehicleAddType.currentIndex === 0 ? "attack" : "amb", dutyVehicleCodeField.text, dutyVehiclePlateField.text)

        contentItem: ColumnLayout {
            spacing: 10

            Label {
                text: "車輛類型"
                color: window.muted
            }
            AppleComboBox {
                id: dutyVehicleAddType
                objectName: "dutyVehicleAddType"
                compact: true
                Layout.fillWidth: true
                model: ["消防車", "救護車"]
                currentIndex: 1
            }
            Label {
                text: "車輛代號"
                color: window.muted
            }
            AppleTextField {
                id: dutyVehicleCodeField
                compact: true
                Layout.fillWidth: true
                placeholderText: "例如：新坡93"
            }
            Label {
                text: "車牌號碼"
                color: window.muted
            }
            AppleTextField {
                id: dutyVehiclePlateField
                compact: true
                Layout.fillWidth: true
                placeholderText: "例如：BSL-9230"
            }
        }
    }

    AppleDialog {
        id: dutyVehicleRemoveDialog
        parent: dutySheetDialog.hostWindow.contentItem
        objectName: "dutyVehicleRemoveDialog"
        anchors.centerIn: parent
        width: Math.min(window.width - 72, 440)
        modal: true
        title: "移除車輛"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "移除車輛"
        acceptTone: "dangerFilled"
        onAccepted: dutySheetDialog.controller.removeVehicleOption(dutyVehicleRemoveType.currentIndex === 0 ? "attack" : "amb", dutyVehicleRemoveValue.currentText)

        contentItem: ColumnLayout {
            spacing: 10

            Label {
                text: "車輛類型"
                color: window.muted
            }
            AppleComboBox {
                id: dutyVehicleRemoveType
                objectName: "dutyVehicleRemoveType"
                compact: true
                Layout.fillWidth: true
                model: ["消防車", "救護車"]
                currentIndex: 1
            }
            Label {
                text: "車輛代號／車牌號碼"
                color: window.muted
            }
            AppleComboBox {
                id: dutyVehicleRemoveValue
                objectName: "dutyVehicleRemoveValue"
                compact: true
                Layout.fillWidth: true
                model: dutyVehicleRemoveType.currentIndex === 0 ? dutySheetDialog.controller.attackOptions : dutySheetDialog.controller.ambOptions
            }
        }
    }

    AppleCalendarButton {
        id: dutyDateCalendar
        objectName: "dutyDateCalendarButton"
        triggerOnly: true
        anchorItem: dutyDateField
        popupParent: dutySheetDialog.hostWindow.contentItem
        dateText: dutyDateField.text
        dateFormat: "slash"
        enabled: !dutySheetDialog.controller.isRunning
        onDateSelected: function (value) {
            dutyDateField.text = value;
        }
    }

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "勤務表登打"
            canClose: dutySheetDialog.canClose
            closeAction: function () {
                dutySheetDialog.close();
            }
        }
        ToolUsageHistory {
            backend: dutySheetDialog.hostWindow.backend
            toolId: "duty_sheet"
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8

                ToolSectionTitle {
                    text: "來源檔案及日期設定"
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    rowSpacing: 8
                    columnSpacing: 8

                    ToolFieldLabel {
                        text: "Excel"
                    }
                    AppleTextField {
                        id: dutyWorkbookField
                        objectName: "dutyWorkbookField"
                        compact: true
                        Layout.fillWidth: true
                        text: dutySheetDialog.controller.workbookPath
                        enabled: !dutySheetDialog.controller.isRunning
                    }
                    ToolBrowseButton {
                        objectName: "dutyWorkbookBrowseButton"
                        enabled: !dutySheetDialog.controller.isRunning
                        onClicked: dutySheetDialog.browseWorkbookRequested()
                    }

                    ToolFieldLabel {
                        text: "日期"
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Layout.columnSpan: 2
                        spacing: 6

                        AppleTextField {
                            id: dutyDateField
                            objectName: "dutyDateField"
                            compact: true
                            Layout.preferredWidth: Design.toolDateFieldWidth
                            text: dutySheetDialog.controller.targetDate
                            enabled: !dutySheetDialog.controller.isRunning
                            clickAction: function () {
                                dutyDateCalendar.openForCurrentDate();
                            }
                        }
                        ToolDateStepButton {
                            objectName: "dutyPreviousDateButton"
                            text: "<"
                            enabled: !dutySheetDialog.controller.isRunning
                            onClicked: dutyDateField.text = window.shiftSlashDate(dutyDateField.text, -1)
                        }
                        ToolDateStepButton {
                            objectName: "dutyNextDateButton"
                            text: ">"
                            enabled: !dutySheetDialog.controller.isRunning
                            onClicked: dutyDateField.text = window.shiftSlashDate(dutyDateField.text, 1)
                        }
                        Item {
                            Layout.fillWidth: true
                        }
                    }

                    Item {
                        Layout.preferredWidth: 0
                    }
                    AppleCheckBox {
                        id: dutyNotificationCheck
                        objectName: "dutyNotificationCheck"
                        Layout.columnSpan: 2
                        text: "完成後發送勤務表截圖"
                        checked: dutySheetDialog.controller.notificationEnabled
                        enabled: !dutySheetDialog.controller.isRunning
                    }
                }
            }
        }

        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8

                ToolSectionTitle {
                    text: "主力車設定"
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: 8
                    columnSpacing: 10

                    ToolFieldLabel {
                        text: "攻擊車"
                    }
                    AppleComboBox {
                        id: dutyAttackCombo
                        objectName: "dutyAttackCombo"
                        compact: true
                        Layout.fillWidth: true
                        editable: true
                        enabled: !dutySheetDialog.controller.isRunning
                        model: dutySheetDialog.controller.attackOptions
                        currentIndex: Math.max(0, model.indexOf(dutySheetDialog.controller.attack))
                    }
                    ToolFieldLabel {
                        text: "中繼車"
                    }
                    AppleComboBox {
                        id: dutyStopCombo
                        objectName: "dutyStopCombo"
                        compact: true
                        Layout.fillWidth: true
                        editable: true
                        enabled: !dutySheetDialog.controller.isRunning
                        model: dutySheetDialog.controller.stopOptions
                        currentIndex: Math.max(0, model.indexOf(dutySheetDialog.controller.stop))
                    }
                    ToolFieldLabel {
                        text: "救護 1 車"
                    }
                    AppleComboBox {
                        id: dutyAmb1Combo
                        objectName: "dutyAmb1Combo"
                        compact: true
                        Layout.fillWidth: true
                        editable: true
                        enabled: !dutySheetDialog.controller.isRunning
                        model: dutySheetDialog.controller.ambOptions
                        currentIndex: Math.max(0, model.indexOf(dutySheetDialog.controller.amb1))
                    }
                    ToolFieldLabel {
                        text: "救護 2 車"
                    }
                    AppleComboBox {
                        id: dutyAmb2Combo
                        objectName: "dutyAmb2Combo"
                        compact: true
                        Layout.fillWidth: true
                        editable: true
                        enabled: !dutySheetDialog.controller.isRunning
                        model: dutySheetDialog.controller.ambOptions
                        currentIndex: Math.max(0, model.indexOf(dutySheetDialog.controller.amb2))
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 10

                    Item {
                        Layout.preferredWidth: Design.toolFieldLabelWidth
                    }
                    RowLayout {
                        id: dutyVehicleButtons
                        Layout.fillWidth: true
                        spacing: 8

                        ToolAddButton {
                            objectName: "dutyVehicleAddButton"
                            Layout.fillWidth: true
                            Layout.preferredWidth: 0
                            text: "新增車輛"
                            enabled: !dutySheetDialog.controller.isRunning
                            onClicked: dutyVehicleAddDialog.open()
                        }
                        ToolRemoveButton {
                            objectName: "dutyVehicleRemoveButton"
                            Layout.fillWidth: true
                            Layout.preferredWidth: 0
                            text: "移除車輛"
                            enabled: !dutySheetDialog.controller.isRunning
                            onClicked: dutyVehicleRemoveDialog.open()
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillHeight: true
        }
        ToolStatusBar {
            objectName: "dutySheetStatusBar"
            text: dutySheetDialog.controller.statusText
        }
        ToolRunButton {
            objectName: "dutySheetRunButton"
            Layout.fillWidth: true
            text: dutySheetDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !dutySheetDialog.controller.isRunning
            onClicked: dutySheetDialog.controller.prepareRun(dutyWorkbookField.text, dutyDateField.text, dutyAttackCombo.currentText, dutyStopCombo.currentText, dutyAmb1Combo.currentText, dutyAmb2Combo.currentText, dutyNotificationCheck.checked)
        }
    }

    AppleDialog {
        id: dutySheetConfirmation
        parent: dutySheetDialog.hostWindow.contentItem
        objectName: "dutySheetConfirmation"
        anchors.centerIn: parent
        width: Math.min(window.width - 72, 460)
        modal: true
        title: "確認正式登打"
        standardButtons: Dialog.Yes | Dialog.No
        acceptText: "開始登打"
        onAccepted: dutySheetDialog.controller.confirmRun()
        onRejected: dutySheetDialog.controller.cancelPendingRun()

        Label {
            width: parent.width
            text: dutySheetDialog.controller.confirmationSummary
            color: window.ink
            wrapMode: Text.Wrap
        }
    }

    Connections {
        target: dutySheetDialog.controller

        function onConfirmationRequested() {
            dutySheetConfirmation.open();
        }

        function onErrorOccurred(message) {
            if (dutySheetDialog.errorHandler)
                dutySheetDialog.errorHandler(message);
        }
    }
}
