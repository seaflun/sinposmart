import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../styles"

ToolSidePanel {
    id: dailyVehicleDialog
    required property var controller
    objectName: "dailyVehicleDialog"
    canClose: !dailyVehicleDialog.controller.isRunning

    contentItem: ToolPanelContent {
        ToolPanelHeader {
            text: "車輛保養清點"
            canClose: dailyVehicleDialog.canClose
            closeAction: function () {
                dailyVehicleDialog.close();
            }
        }
        ToolUsageHistory {
            backend: dailyVehicleDialog.hostWindow.backend
            toolId: "daily_vehicle"
        }
        ToolFormCard {
            contentItem: ColumnLayout {
                spacing: 8
                ToolSectionTitle {
                    text: "車輛保養設定"
                }

                Label {
                    objectName: "dailyVehiclePromptText"
                    Layout.fillWidth: true
                    text: "依當日勤務表自動分派上班隊員，使用各隊員帳號執行定期保養及隨車器材清點。"
                    color: Design.muted
                    font.pixelSize: Design.captionSize
                    wrapMode: Text.Wrap
                }
            }
        }
        Item {
            Layout.fillHeight: true
        }
        ToolStatusBar {
            objectName: "dailyVehicleStatusBar"
            text: dailyVehicleDialog.controller.statusText
            onDetailsRequested: function(message) {
                dailyVehicleDialog.hostWindow.showErrorDetails("車輛保養清點錯誤", message)
            }
        }
        ToolRunButton {
            objectName: "dailyVehicleRunButton"
            Layout.fillWidth: true
            text: dailyVehicleDialog.controller.isRunning ? "啟動中..." : "啟動登打"
            enabled: !dailyVehicleDialog.controller.isRunning
                     && dailyVehicleDialog.hostWindow.backend.sessionController.actorNo.trim().length > 0
                     && !dailyVehicleDialog.hostWindow.backend.readOnlyAcceptance
            onClicked: {
                if (!dailyVehicleDialog.hostWindow.backend.readOnlyAcceptance) {
                    dailyVehicleDialog.controller.prepareRun()
                }
            }
        }
    }
}
