import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: dutySheetDialog
    required property var controller
    property alias workbookPath: dutyWorkbookField.text
    property string personnelDeductionEditingId: ""
    signal browseWorkbookRequested
    objectName: "dutySheetDialog"
    canClose: !dutySheetDialog.controller.isRunning

    function resetPersonnelDeductionForm() {
        personnelDeductionEditingId = "";
        dutyPersonnelDeductionPeopleField.text = "";
        dutyPersonnelDeductionStartDateField.text = dutyDateField.text;
        dutyPersonnelDeductionEndDateField.text = dutyDateField.text;
        dutyPersonnelDeductionReasonField.text = "";
    }

    function editPersonnelDeduction(record) {
        if (!controller.canEditPersonnelDeductions)
            return;
        personnelDeductionEditingId = record.id;
        dutyPersonnelDeductionPeopleField.text = record.people.join("、");
        dutyPersonnelDeductionStartDateField.text = record.start_date;
        dutyPersonnelDeductionEndDateField.text = record.end_date;
        dutyPersonnelDeductionReasonField.text = record.reason;
        dutyPersonnelDeductionPeopleField.forceActiveFocus();
        var flickable = dutySheetSettingsScroll.contentItem;
        flickable.contentY = Math.max(0, Math.min(dutyPersonnelDeductionCard.y,
                                                flickable.contentHeight - flickable.height));
    }

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
            dutyVehicleAddFunction.currentIndex = 0;
        }
        onAccepted: {
            if (!dutySheetDialog.hostWindow.backend.readOnlyAcceptance) {
                dutySheetDialog.controller.addVehicleOption(dutyVehicleAddType.currentIndex === 0 ? (dutyVehicleAddFunction.currentIndex === 0 ? "attack" : "stop") : "amb", dutyVehicleCodeField.text, dutyVehiclePlateField.text)
            }
        }

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
                visible: dutyVehicleAddType.currentIndex === 0
                text: "車輛功能"
                color: window.muted
            }
            AppleComboBox {
                id: dutyVehicleAddFunction
                objectName: "dutyVehicleAddFunction"
                visible: dutyVehicleAddType.currentIndex === 0
                compact: true
                Layout.fillWidth: true
                model: ["攻擊車", "中繼車"]
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
        onAccepted: {
            if (!dutySheetDialog.hostWindow.backend.readOnlyAcceptance) {
                dutySheetDialog.controller.removeVehicleOption(dutyVehicleRemoveType.currentIndex === 0 ? (dutyVehicleRemoveFunction.currentIndex === 0 ? "attack" : "stop") : "amb", dutyVehicleRemoveValue.currentText)
            }
        }

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
                visible: dutyVehicleRemoveType.currentIndex === 0
                text: "車輛功能"
                color: window.muted
            }
            AppleComboBox {
                id: dutyVehicleRemoveFunction
                objectName: "dutyVehicleRemoveFunction"
                visible: dutyVehicleRemoveType.currentIndex === 0
                compact: true
                Layout.fillWidth: true
                model: ["攻擊車", "中繼車"]
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
                model: dutyVehicleRemoveType.currentIndex === 0 ? (dutyVehicleRemoveFunction.currentIndex === 0 ? dutySheetDialog.controller.attackOptions : dutySheetDialog.controller.stopOptions) : dutySheetDialog.controller.ambOptions
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

    AppleCalendarButton {
        id: personnelDeductionStartCalendar
        objectName: "dutyPersonnelDeductionStartCalendarButton"
        triggerOnly: true
        anchorItem: dutyPersonnelDeductionStartDateField
        popupParent: dutySheetDialog.hostWindow.contentItem
        dateText: dutyPersonnelDeductionStartDateField.text
        dateFormat: "slash"
        enabled: dutySheetDialog.controller.canEditPersonnelDeductions
        onDateSelected: function (value) {
            dutyPersonnelDeductionStartDateField.text = value;
        }
    }

    AppleCalendarButton {
        id: personnelDeductionEndCalendar
        objectName: "dutyPersonnelDeductionEndCalendarButton"
        triggerOnly: true
        anchorItem: dutyPersonnelDeductionEndDateField
        popupParent: dutySheetDialog.hostWindow.contentItem
        dateText: dutyPersonnelDeductionEndDateField.text
        dateFormat: "slash"
        enabled: dutySheetDialog.controller.canEditPersonnelDeductions
        onDateSelected: function (value) {
            dutyPersonnelDeductionEndDateField.text = value;
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
        ScrollView {
            id: dutySheetSettingsScroll
            objectName: "dutySheetSettingsScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: dutySheetSettingsScroll.availableWidth
                spacing: 10

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
                                         && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
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
                                    onTextChanged: {
                                        if (!dutySheetDialog.personnelDeductionEditingId) {
                                            dutyPersonnelDeductionStartDateField.text = text;
                                            dutyPersonnelDeductionEndDateField.text = text;
                                        }
                                    }
                                    enabled: !dutySheetDialog.controller.isRunning
                                             && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
                                    clickAction: function () {
                                        dutyDateCalendar.openForCurrentDate();
                                    }
                                }
                                ToolDateStepButton {
                                    objectName: "dutyPreviousDateButton"
                                    text: "<"
                                    enabled: !dutySheetDialog.controller.isRunning
                                             && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
                                    onClicked: dutyDateField.text = window.shiftSlashDate(dutyDateField.text, -1)
                                }
                                ToolDateStepButton {
                                    objectName: "dutyNextDateButton"
                                    text: ">"
                                    enabled: !dutySheetDialog.controller.isRunning
                                             && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
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
                                onToggled: dutySheetDialog.controller.setNotificationEnabled(checked)
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
                                             && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
                                    onClicked: dutyVehicleAddDialog.open()
                                }
                                ToolRemoveButton {
                                    objectName: "dutyVehicleRemoveButton"
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 0
                                    text: "移除車輛"
                                    enabled: !dutySheetDialog.controller.isRunning
                                             && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
                                    onClicked: dutyVehicleRemoveDialog.open()
                                }
                            }
                        }
                    }
                }

                ToolFormCard {
                    id: dutyPersonnelDeductionCard
                    objectName: "dutyPersonnelDeductionCard"
                    contentItem: ColumnLayout {
                        spacing: 8

                        ToolSectionTitle {
                            text: "人力扣除"
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: 2
                            rowSpacing: 8
                            columnSpacing: 10

                            ToolFieldLabel {
                                text: "人員"
                            }
                            AppleTextField {
                                id: dutyPersonnelDeductionPeopleField
                                objectName: "dutyPersonnelDeductionPeopleField"
                                compact: true
                                Layout.fillWidth: true
                                placeholderText: "20、22"
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                            }
                            ToolFieldLabel {
                                text: "開始日期"
                            }
                            AppleTextField {
                                id: dutyPersonnelDeductionStartDateField
                                objectName: "dutyPersonnelDeductionStartDateField"
                                compact: true
                                Layout.fillWidth: true
                                text: dutyDateField.text
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                clickAction: function () {
                                    personnelDeductionStartCalendar.openForCurrentDate();
                                }
                            }
                            ToolFieldLabel {
                                text: "結束日期"
                            }
                            AppleTextField {
                                id: dutyPersonnelDeductionEndDateField
                                objectName: "dutyPersonnelDeductionEndDateField"
                                compact: true
                                Layout.fillWidth: true
                                text: dutyDateField.text
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                clickAction: function () {
                                    personnelDeductionEndCalendar.openForCurrentDate();
                                }
                            }
                            ToolFieldLabel {
                                text: "原因"
                            }
                            AppleTextField {
                                id: dutyPersonnelDeductionReasonField
                                objectName: "dutyPersonnelDeductionReasonField"
                                compact: true
                                Layout.fillWidth: true
                                placeholderText: "例如：TP訓"
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            Item {
                                Layout.fillWidth: true
                            }
                            AppleButton {
                                objectName: "dutyPersonnelDeductionCancelButton"
                                implicitHeight: Design.toolSmallButtonHeight
                                text: "取消編輯"
                                visible: dutySheetDialog.personnelDeductionEditingId.length > 0
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                onClicked: dutySheetDialog.resetPersonnelDeductionForm()
                            }
                            ToolAddButton {
                                objectName: "dutyPersonnelDeductionSaveButton"
                                text: dutySheetDialog.personnelDeductionEditingId ? "儲存" : "新增"
                                enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                onClicked: {
                                    if (dutySheetDialog.controller.savePersonnelDeduction(
                                            dutyPersonnelDeductionPeopleField.text,
                                            dutyPersonnelDeductionStartDateField.text,
                                            dutyPersonnelDeductionEndDateField.text,
                                            dutyPersonnelDeductionReasonField.text,
                                            dutySheetDialog.personnelDeductionEditingId)) {
                                        dutySheetDialog.resetPersonnelDeductionForm();
                                    }
                                }
                            }
                        }
                        Repeater {
                            objectName: "dutyPersonnelDeductionRepeater"
                            model: dutySheetDialog.controller.personnelDeductions

                            ColumnLayout {
                                id: personnelDeductionRow
                                required property var modelData
                                required property int index
                                objectName: "dutyPersonnelDeductionRow_" + index
                                Layout.fillWidth: true
                                spacing: 8

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: Design.borderWidth
                                    color: Design.divider
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        spacing: 4

                                        Label {
                                            Layout.fillWidth: true
                                            text: personnelDeductionRow.modelData.people.join("、")
                                                  + " · " + personnelDeductionRow.modelData.reason
                                            textFormat: Text.PlainText
                                            font.pixelSize: Design.bodySize
                                            color: window.ink
                                            wrapMode: Text.WrapAnywhere
                                        }
                                        Label {
                                            Layout.fillWidth: true
                                            text: personnelDeductionRow.modelData.start_date
                                                  + "–" + personnelDeductionRow.modelData.end_date
                                            textFormat: Text.PlainText
                                            font.pixelSize: Design.captionSize
                                            color: window.muted
                                            wrapMode: Text.WrapAnywhere
                                        }
                                    }
                                    AppleButton {
                                        objectName: "dutyPersonnelDeductionEditButton_" + personnelDeductionRow.index
                                        implicitHeight: Design.toolSmallButtonHeight
                                        text: "編輯"
                                        enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                        onClicked: dutySheetDialog.editPersonnelDeduction(personnelDeductionRow.modelData)
                                    }
                                    ToolRemoveButton {
                                        objectName: "dutyPersonnelDeductionRemoveButton_" + personnelDeductionRow.index
                                        text: "移除"
                                        enabled: dutySheetDialog.controller.canEditPersonnelDeductions
                                        onClicked: {
                                            var panel = dutySheetDialog;
                                            var recordId = personnelDeductionRow.modelData.id;
                                            var wasEditing = panel.personnelDeductionEditingId === recordId;
                                            if (panel.controller.removePersonnelDeduction(recordId) && wasEditing) {
                                                panel.resetPersonnelDeductionForm();
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        ToolStatusBar {
            objectName: "dutySheetStatusBar"
            text: dutySheetDialog.controller.statusText
            onDetailsRequested: function(message) {
                dutySheetDialog.hostWindow.showErrorDetails("勤務表登打錯誤", message)
            }
        }
        ToolRunButton {
            objectName: "dutySheetRunButton"
            Layout.fillWidth: true
            text: dutySheetDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !dutySheetDialog.controller.isRunning
                     && !dutySheetDialog.hostWindow.backend.readOnlyAcceptance
            onClicked: {
                if (!dutySheetDialog.hostWindow.backend.readOnlyAcceptance) {
                    dutySheetDialog.controller.prepareRun(dutyWorkbookField.text, dutyDateField.text, dutyAttackCombo.currentText, dutyStopCombo.currentText, dutyAmb1Combo.currentText, dutyAmb2Combo.currentText, dutySheetDialog.controller.notificationEnabled)
                }
            }
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
        onAccepted: {
            if (!dutySheetDialog.hostWindow.backend.readOnlyAcceptance) {
                dutySheetDialog.controller.confirmRun()
            }
        }
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
    }
}
