pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: workLogSettingsDialog
    required property var controller
    objectName: "workLogSettingsDialog"
    parent: hostWindow.contentItem

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            objectName: "workLogSettingsHeader"
            text: "工作紀錄預設內容"
            closeAction: function () {
                workLogSettingsDialog.close();
            }
        }

        ScrollView {
            id: workLogSettingsScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: workLogSettingsScroll.availableWidth
                spacing: 8

                ToolFormCard {
                    objectName: "workLogDefaultsCard"
                    contentItem: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 5

                        ToolSectionTitle {
                            text: "工作紀錄預設"
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 88
                                text: "無線電"
                                color: Design.text
                                font.pixelSize: Design.captionSize
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "radio_count"
                                labelText: "良好"
                                unitText: "支"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 88
                                text: "消防及救護車"
                                color: Design.text
                                font.pixelSize: Design.captionSize
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "emergency_vehicles_in_station"
                                labelText: "在隊"
                                unitText: "台"
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "emergency_vehicles_repair"
                                labelText: "報修"
                                unitText: "台"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 88
                                text: "後勤車"
                                color: Design.text
                                font.pixelSize: Design.captionSize
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "support_vehicles_in_station"
                                labelText: "在隊"
                                unitText: "台"
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "support_vehicles_out"
                                labelText: "出勤"
                                unitText: "台"
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "support_vehicles_repair"
                                labelText: "報修"
                                unitText: "台"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 88
                                text: "救災器材"
                                color: Design.text
                                font.pixelSize: Design.captionSize
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "rescue_equipment_in_station"
                                labelText: "在隊"
                                unitText: "台"
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "rescue_equipment_out"
                                labelText: "出勤"
                                unitText: "台"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.preferredWidth: 88
                                text: "TIC"
                                color: Design.text
                                font.pixelSize: Design.captionSize
                            }
                            WorkLogValueControl {
                                settingsController: workLogSettingsDialog.controller
                                settingKey: "tic_count"
                                labelText: "隊上"
                                unitText: "支"
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                        Label {
                            text: "重要記事"
                            color: Design.controlText
                            font.pixelSize: Design.captionSize
                        }
                        AppleTextArea {
                            id: workLogNoteField
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            text: workLogSettingsDialog.controller.importantNote
                            onActiveFocusChanged: {
                                if (!activeFocus)
                                    workLogSettingsDialog.controller.setImportantNote(text);
                            }
                        }
                    }
                }
                ToolFormCard {
                    objectName: "workLogCaseCard"
                    Layout.fillWidth: true
                    contentItem: ColumnLayout {
                        id: caseSettingsLayout
                        spacing: 8

                        ToolSectionTitle {
                            text: "未返隊案件出勤估算"
                        }
                        Label {
                            Layout.fillWidth: true
                            visible: workLogSettingsDialog.controller.caseItems.length === 0
                            text: "目前沒有查到未返隊案件；登入查詢後會由案件帶入。"
                            color: workLogSettingsDialog.hostWindow.muted
                            font.pixelSize: Design.bodySize
                            wrapMode: Text.Wrap
                        }
                        Repeater {
                            objectName: "caseSettingsRepeater"
                            model: workLogSettingsDialog.controller.caseItems

                            RowLayout {
                                id: caseSettingsRow
                                objectName: "caseSettingsRow"
                                required property var modelData
                                Layout.fillWidth: true
                                spacing: 8

                                Label {
                                    Layout.fillWidth: true
                                    text: caseSettingsRow.modelData.label
                                    color: workLogSettingsDialog.hostWindow.ink
                                    elide: Text.ElideRight
                                }
                                AppleTextField {
                                    objectName: "caseVehicleCountField"
                                    Layout.preferredWidth: 42
                                    Layout.preferredHeight: 28
                                    Accessible.name: caseSettingsRow.modelData.label + " 車數"
                                    text: String(caseSettingsRow.modelData.count)
                                    horizontalAlignment: TextInput.AlignHCenter
                                    validator: IntValidator {
                                        bottom: 0
                                    }
                                    onTextEdited: {
                                        if (text.length > 0 && acceptableInput)
                                            workLogSettingsDialog.controller.setCaseVehicleCount(caseSettingsRow.modelData.key, text);
                                    }
                                    onEditingFinished: workLogSettingsDialog.controller.setCaseVehicleCount(caseSettingsRow.modelData.key, text)
                                }
                                Label {
                                    text: "台"
                                    color: workLogSettingsDialog.hostWindow.muted
                                }
                            }
                        }
                    }
                }
                ToolFormCard {
                    objectName: "workLogPreviewCard"
                    contentItem: ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        ToolSectionTitle {
                            text: "工作紀錄預覽"
                        }
                        Label {
                            objectName: "workLogPreviewText"
                            Layout.fillWidth: true
                            Layout.preferredHeight: implicitHeight
                            text: workLogSettingsDialog.controller.previewText.length > 0 ? workLogSettingsDialog.controller.previewText : workLogSettingsDialog.controller.statusText
                            color: Design.infoText
                            font.pixelSize: Design.captionSize
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            AppleButton {
                Layout.preferredWidth: Design.workLogRestoreButtonWidth
                Layout.preferredHeight: Design.toolActionButtonHeight
                text: "還原預設"
                onClicked: workLogSettingsDialog.controller.resetDefaults()
            }
            Item {
                Layout.fillWidth: true
            }
            AppleButton {
                objectName: "workLogSettingsDiscardButton"
                Layout.preferredWidth: Design.workLogActionButtonWidth
                Layout.preferredHeight: Design.toolActionButtonHeight
                text: "取消"
                onClicked: workLogSettingsDialog.close()
            }
            PrimaryButton {
                objectName: "workLogSettingsSaveButton"
                Layout.preferredWidth: Design.workLogActionButtonWidth
                Layout.preferredHeight: Design.toolActionButtonHeight
                text: "儲存"
                onClicked: {
                    workLogSettingsDialog.controller.setImportantNote(workLogNoteField.text);
                    if (workLogSettingsDialog.controller.save())
                        workLogSettingsDialog.close();
                }
            }
        }
    }
}
