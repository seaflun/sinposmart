import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: monthlyBaseDialog
    required property var controller
    required property var sessionController
    objectName: "monthlyBaseDialog"
    canClose: !monthlyBaseDialog.controller.isRunning

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "勤務基準表登打"
            canClose: monthlyBaseDialog.canClose
            closeAction: function () {
                monthlyBaseDialog.close();
            }
        }
        ToolUsageHistory {
            backend: monthlyBaseDialog.hostWindow.backend
            toolId: "monthly_base"
            currentOperatorOnly: true
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8

                ToolSectionTitle {
                    objectName: "monthlySourceTitle"
                    text: "來源及月份設定"
                }
                Label {
                    Layout.fillWidth: true
                    text: "登打以 Google 試算表為主；若後續有更改假別，請自行修正。"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                    wrapMode: Text.Wrap
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true

                        ToolFieldLabel {
                            text: "來源"
                        }
                        Label {
                            objectName: "monthlySourceLabel"
                            Layout.fillWidth: true
                            Layout.minimumWidth: 0
                            text: "Google 試算表 / 輪休基準表"
                            wrapMode: Text.Wrap
                        }
                    }
                    ToolBrowseButton {
                        objectName: "monthlySourceOpenButton"
                        Layout.alignment: Qt.AlignRight
                        Layout.minimumWidth: Design.monthlySourceOpenButtonWidth
                        Layout.preferredWidth: Design.monthlySourceOpenButtonWidth
                        Layout.maximumWidth: Design.monthlySourceOpenButtonWidth
                        implicitHeight: Design.toolBrowseButtonHeight
                        leftPadding: 10
                        rightPadding: 10
                        enabled: !monthlyBaseDialog.controller.isRunning
                        text: "開啟試算表"
                        onClicked: Qt.openUrlExternally("https://docs.google.com/spreadsheets/d/1m-zy4KNR8_GMO94dYtFotyWPIvuT_tt32J9l7hhGZt0/edit#gid=1587057625")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ToolFieldLabel {
                        text: "Google 試算表月份"
                    }
                    Label {
                        objectName: "monthlySourceMonthLabel"
                        Layout.fillWidth: true
                        text: monthlyBaseDialog.controller.monthlySourcePeriod
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
        Item {
            Layout.fillHeight: true
        }
        ToolStatusBar {
            objectName: "monthlyBaseStatusBar"
            text: monthlyBaseDialog.controller.statusText
            onDetailsRequested: function(message) {
                monthlyBaseDialog.hostWindow.showErrorDetails("勤務基準表登打錯誤", message)
            }
        }
        ToolRunButton {
            objectName: "monthlyBaseRunButton"
            Layout.fillWidth: true
            text: monthlyBaseDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !monthlyBaseDialog.controller.isRunning
                     && monthlyBaseDialog.controller.monthlySourceReady
            onClicked: monthlyBaseDialog.controller.prepareMonthlyRun()
        }
    }
}
