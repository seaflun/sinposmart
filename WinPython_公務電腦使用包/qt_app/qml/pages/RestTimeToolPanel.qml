import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: restTimeDialog
    required property var controller
    signal browseWorkbookRequested
    objectName: "restTimeDialog"
    canClose: !restTimeDialog.controller.isRunning

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "休息時間登打"
            canClose: restTimeDialog.canClose
            closeAction: function () {
                restTimeDialog.close();
            }
        }
        ToolUsageHistory {
            backend: restTimeDialog.hostWindow.backend
            toolId: "rest_time"
            currentOperatorOnly: true
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8

                ToolSectionTitle {
                    objectName: "restWorkbookTitle"
                    text: "來源檔案及月份設定"
                }
                Label {
                    Layout.fillWidth: true
                    text: "登打以勤務表為主；若個人有補欠時數歸還，請自行修正。"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.fillWidth: true
                    ToolFieldLabel {
                        text: "Excel"
                    }
                    AppleTextField {
                        id: restWorkbookField
                        objectName: "restWorkbookField"
                        compact: true
                        Layout.fillWidth: true
                        text: restTimeDialog.controller.restWorkbookPath
                        enabled: !restTimeDialog.controller.isRunning
                    }
                    ToolBrowseButton {
                        objectName: "restWorkbookBrowseButton"
                        enabled: !restTimeDialog.controller.isRunning
                        onClicked: restTimeDialog.browseWorkbookRequested()
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ToolFieldLabel {
                        text: "年月"
                    }
                    Label {
                        text: restTimeDialog.controller.rocYear
                    }
                    Label {
                        text: "年"
                    }
                    ToolMonthCombo {
                        id: restMonthCombo
                        objectName: "restMonthCombo"
                        enabled: !restTimeDialog.controller.isRunning
                        model: restTimeDialog.controller.monthOptions
                        currentIndex: Math.max(0, model.indexOf(restTimeDialog.controller.restMonth))
                    }
                    Label {
                        text: "月"
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }
            }
        }
        Item {
            Layout.fillHeight: true
        }
        ToolStatusBar {
            objectName: "restTimeStatusBar"
            text: restTimeDialog.controller.statusText
            onDetailsRequested: function(message) {
                restTimeDialog.hostWindow.showErrorDetails("休息時間登打錯誤", message)
            }
        }
        ToolRunButton {
            objectName: "restTimeRunButton"
            Layout.fillWidth: true
            text: restTimeDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !restTimeDialog.controller.isRunning
            onClicked: restTimeDialog.controller.prepareRestRun(restWorkbookField.text, restMonthCombo.currentText)
        }
    }
}
